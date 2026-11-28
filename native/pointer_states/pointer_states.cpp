// The final hidden state of every prompt token, from stock llama.cpp (libllama +
// libmtmd): what the CaptchaKraken pointer heads read. One process serves many
// requests, one JSON line each way.
//
//   pointer_states MODEL.gguf MMPROJ.gguf [--threads N] [--ctx N] [--batch N] [--device PCI | --cpu]
//   pointer_states --list-devices
//
// --device runs on the GPU at that PCI address (0000:01:00.0), the one key that
// nvidia-smi and Vulkan agree on; their indexes differ. Without it, every GPU is used.
//
//   stdin:  {"prompt": "...<__media__>...", "media": [{"rgb": PATH, "w": W, "h": H, "video": false}], "out": PATH}
//   stdout: {"ok": true, "n_embd": D, "ms": T, "chunks": [{"text": [ids]}, {"media": N, "grid": [W, H]}, ...]}
//           {"ok": false, "error": "..."}
//
// Each "rgb" file is raw RGB bytes, W*H*3, so no image codec sits between the
// caller's pixels and the vision encoder. Two adjacent video frames are one
// temporal patch, as Qwen merges them. OUT gets float32 [n_tokens, D] in prompt
// order; "chunks" is the token layout behind it, so the caller can check it
// against the processor the model was trained with.
#include "llama.h"
#include "mtmd.h"
#include "mtmd-helper.h"

#include <nlohmann/json.hpp>

#include <cctype>
#include <chrono>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <iterator>
#include <memory>
#include <string>
#include <vector>

using json = nlohmann::ordered_json;

struct bitmap_deleter { void operator()(mtmd_bitmap * b) const { mtmd_bitmap_free(b); } };
struct chunks_deleter { void operator()(mtmd_input_chunks * c) const { mtmd_input_chunks_free(c); } };
using bitmap_ptr = std::unique_ptr<mtmd_bitmap, bitmap_deleter>;
using chunks_ptr = std::unique_ptr<mtmd_input_chunks, chunks_deleter>;

static bitmap_ptr load_bitmap(const json & m) {
    const int w = m.at("w"), h = m.at("h");
    std::ifstream f(m.at("rgb").get<std::string>(), std::ios::binary);
    const std::vector<unsigned char> rgb((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    if (rgb.size() != (size_t) w * h * 3) {
        throw std::runtime_error("media is " + std::to_string(rgb.size()) + " bytes, not " + std::to_string(w) + "x" +
                                 std::to_string(h) + "x3");
    }
    bitmap_ptr b(mtmd_bitmap_init(w, h, rgb.data()));
    if (m.value("video", false)) {
        mtmd_bitmap_set_mergeable(b.get(), true);
        mtmd_bitmap_set_is_video(b.get(), true);
    }
    return b;
}

static json media_chunk(const mtmd_input_chunk * chunk) {
    const mtmd_image_tokens * img = mtmd_input_chunk_get_tokens_image(chunk);
    const size_t n = mtmd_image_tokens_get_n_tokens(img);
    std::vector<mtmd_decoder_pos> pos(n);
    mtmd_helper_image_get_decoder_pos(img, 0, pos.data());
    uint32_t gx = 0, gy = 0;
    for (const auto & p : pos) {
        gx = std::max(gx, p.x + 1);
        gy = std::max(gy, p.y + 1);
    }
    return {{"media", n}, {"grid", {gx, gy}}};
}

static json solve(mtmd_context * mctx, llama_context * lctx, int n_embd, int n_batch, const json & req) {
    std::vector<bitmap_ptr> owned;
    for (const auto & m : req.at("media")) owned.push_back(load_bitmap(m));
    std::vector<const mtmd_bitmap *> bitmaps;
    for (const auto & b : owned) bitmaps.push_back(b.get());

    const std::string prompt = req.at("prompt");
    const mtmd_input_text text = {prompt.c_str(), prompt.size(), /*add_special*/ false, /*parse_special*/ true};
    chunks_ptr chunks(mtmd_input_chunks_init());
    if (mtmd_tokenize(mctx, chunks.get(), &text, bitmaps.data(), bitmaps.size()) != 0) {
        throw std::runtime_error("tokenize failed: the prompt's media markers and the media do not match");
    }

    llama_memory_clear(llama_get_memory(lctx), true);
    std::vector<float> states;
    json layout = json::array();
    llama_pos n_past = 0;
    for (size_t c = 0; c < mtmd_input_chunks_size(chunks.get()); c++) {
        const mtmd_input_chunk * chunk = mtmd_input_chunks_get(chunks.get(), c);
        const int n_tok = (int) mtmd_input_chunk_get_n_tokens(chunk);
        // A chunk decoded in two batches would leave only the second batch's states readable.
        if (n_tok > n_batch) throw std::runtime_error("a chunk of " + std::to_string(n_tok) + " tokens exceeds --batch");
        if (mtmd_helper_eval_chunk_single(mctx, lctx, chunk, n_past, 0, n_batch, false, &n_past) != 0) {
            throw std::runtime_error("decode failed");
        }
        for (int i = 0; i < n_tok; i++) {
            const float * e = llama_get_embeddings_ith(lctx, i);
            if (!e) throw std::runtime_error("no state for token " + std::to_string(i));
            states.insert(states.end(), e, e + n_embd);
        }
        if (mtmd_input_chunk_get_type(chunk) == MTMD_INPUT_CHUNK_TYPE_TEXT) {
            size_t n = 0;
            const llama_token * ids = mtmd_input_chunk_get_tokens_text(chunk, &n);
            layout.push_back({{"text", std::vector<llama_token>(ids, ids + n)}});
        } else {
            layout.push_back(media_chunk(chunk));
        }
    }

    std::ofstream out(req.at("out").get<std::string>(), std::ios::binary);
    out.write((const char *) states.data(), states.size() * sizeof(float));
    if (!out) throw std::runtime_error("cannot write the states");
    return {{"ok", true}, {"n_embd", n_embd}, {"chunks", layout}};
}

static std::string lower(std::string s) {
    for (auto & c : s) c = (char) std::tolower((unsigned char) c);
    return s;
}

// The GPUs this machine's drivers expose, as one JSON line: what `fetch` checks before it installs.
static json gpu_devices() {
    json out = json::array();
    for (size_t i = 0; i < ggml_backend_dev_count(); i++) {
        ggml_backend_dev_t dev = ggml_backend_dev_get(i);
        ggml_backend_dev_props p;
        ggml_backend_dev_get_props(dev, &p);
        if (p.type != GGML_BACKEND_DEVICE_TYPE_GPU && p.type != GGML_BACKEND_DEVICE_TYPE_IGPU) continue;
        out.push_back({{"name", p.description ? p.description : p.name}, {"pci", p.device_id ? p.device_id : ""},
                       {"total_mib", p.memory_total >> 20}, {"free_mib", p.memory_free >> 20}});
    }
    return out;
}

static ggml_backend_dev_t find_device(const std::string & pci) {
    for (size_t i = 0; i < ggml_backend_dev_count(); i++) {
        ggml_backend_dev_t dev = ggml_backend_dev_get(i);
        ggml_backend_dev_props p;
        ggml_backend_dev_get_props(dev, &p);
        if (p.device_id && lower(p.device_id) == lower(pci)) return dev;
    }
    return nullptr;
}

int main(int argc, char ** argv) {
    if (argc == 2 && std::string(argv[1]) == "--list-devices") {
        llama_backend_init();
        std::cout << json{{"gpus", gpu_devices()}}.dump() << std::endl;
        return 0;
    }
    if (argc < 3) {
        fprintf(stderr, "usage: %s MODEL.gguf MMPROJ.gguf [--threads N] [--ctx N] [--batch N] [--device PCI | --cpu]\n"
                        "       %s --list-devices\n", argv[0], argv[0]);
        return 2;
    }
    // The batch bounds one chunk (an image, a frame pair, a run of text), not the prompt.
    // It costs a vocabulary-wide logits row per token, which per-token states cannot skip.
    int n_threads = 4, n_ctx = 16384, n_batch = 1024;
    bool gpu = true;
    std::string pci;
    for (int i = 3; i < argc; i++) {
        const std::string a = argv[i];
        if (a == "--threads" && i + 1 < argc) n_threads = std::stoi(argv[++i]);
        else if (a == "--ctx" && i + 1 < argc) n_ctx = std::stoi(argv[++i]);
        else if (a == "--batch" && i + 1 < argc) n_batch = std::stoi(argv[++i]);
        else if (a == "--device" && i + 1 < argc) pci = argv[++i];
        else if (a == "--cpu") gpu = false;
        else { fprintf(stderr, "unknown argument %s\n", a.c_str()); return 2; }
    }

    llama_backend_init();
    llama_model_params mp = llama_model_default_params();
    mp.n_gpu_layers = gpu ? 999 : 0;
    ggml_backend_dev_t devices[2] = {nullptr, nullptr};
    if (gpu && !pci.empty()) {
        devices[0] = find_device(pci);
        if (!devices[0]) {
            fprintf(stderr, "no GPU at PCI %s; these are: %s\n", pci.c_str(), gpu_devices().dump().c_str());
            return 1;
        }
        mp.devices = devices;
    }
    llama_model * model = llama_model_load_from_file(argv[1], mp);
    if (!model) { fprintf(stderr, "failed to load %s\n", argv[1]); return 1; }

    llama_context_params cp = llama_context_default_params();
    cp.n_ctx = n_ctx;
    cp.n_batch = n_batch;
    cp.n_ubatch = n_batch;
    cp.n_threads = n_threads;
    cp.n_threads_batch = n_threads;
    cp.embeddings = true;
    cp.pooling_type = LLAMA_POOLING_TYPE_NONE;
    llama_context * lctx = llama_init_from_model(model, cp);
    if (!lctx) { fprintf(stderr, "failed to create a %d-token context\n", n_ctx); return 1; }

    mtmd_context_params mcp = mtmd_context_params_default();
    mcp.use_gpu = gpu;
    mcp.device = devices[0];
    mcp.n_threads = n_threads;
    mcp.print_timings = false;
    mcp.media_marker = mtmd_default_marker();
    mtmd_context * mctx = mtmd_init_from_file(argv[2], model, mcp);
    if (!mctx) { fprintf(stderr, "failed to load %s\n", argv[2]); return 1; }

    const int n_embd = llama_model_n_embd(model);
    std::cout << json{{"ready", true}, {"n_embd", n_embd}, {"marker", mtmd_default_marker()}}.dump() << std::endl;
    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.empty()) continue;
        const auto t0 = std::chrono::steady_clock::now();
        json reply;
        try {
            reply = solve(mctx, lctx, n_embd, n_batch, json::parse(line));
        } catch (const std::exception & e) {
            reply = {{"ok", false}, {"error", e.what()}};
        }
        reply["ms"] = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - t0).count();
        std::cout << reply.dump() << std::endl;
    }
    mtmd_free(mctx);
    llama_free(lctx);
    llama_model_free(model);
    return 0;
}
