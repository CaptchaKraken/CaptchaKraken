"""The pointer model inside vLLM: one prefill, the heads in the pooler, no decoding.

Registered as a vLLM general plugin (`pyproject.toml`'s `vllm.general_plugins`
entry point), so `vllm serve <checkpoint> --runner pooling` and
`vllm.LLM(<checkpoint>, runner="pooling")` find it by the architecture name an
exported checkpoint declares, `CaptchaPointerForConditionalGeneration`.

The model is vLLM's own Qwen3.5 with one extra module, `pointer_heads` (the
client's `heads.Heads`, loaded from the checkpoint's `pointer_heads.*` weights).
Its pooler gathers each request's last hidden states across chunked prefill
(vLLM's `AllPool`), finds the positions it reads from the prompt's token ids,
and returns the packed decision vector `layout.unpack` reads. Nothing is
sampled and no token is generated.
"""
from __future__ import annotations

from collections.abc import Set

ARCHITECTURE = "CaptchaPointerForConditionalGeneration"


def register() -> None:
    from vllm import ModelRegistry
    if ARCHITECTURE not in ModelRegistry.get_supported_archs():
        ModelRegistry.register_model(ARCHITECTURE, "captchakraken.pointer.vllm_plugin:PointerQwen3_5")


def _model_class():
    import torch
    from vllm.model_executor.layers.pooler.abstract import Pooler
    from vllm.model_executor.layers.pooler.common import PoolingParamsUpdate
    from vllm.model_executor.layers.pooler.tokwise.methods import AllPool
    from vllm.model_executor.models.interfaces_base import default_pooling_type
    from vllm.model_executor.models.qwen3_5 import Qwen3_5ForConditionalGeneration, Qwen3_5ProcessingInfo
    from vllm.model_executor.models.qwen3_vl import Qwen3VLDummyInputsBuilder, Qwen3VLMultiModalProcessor
    from vllm.multimodal import MULTIMODAL_REGISTRY

    from . import layout as L
    from .heads import Heads, Positions

    class PointerPooler(Pooler):
        def __init__(self, model):
            super().__init__()
            self.gather = AllPool()
            # Not a submodule: the model owns the heads and the output matrix.
            self.__dict__["model"] = model

        def get_supported_tasks(self) -> Set:
            return {"embed"}

        def get_pooling_updates(self, task):
            return PoolingParamsUpdate(requires_token_ids=True)

        def forward(self, hidden_states, pooling_metadata):
            m = self.model
            out = []
            for h, ids in zip(self.gather(hidden_states, pooling_metadata),
                              pooling_metadata.get_prompt_token_ids_cpu()):
                if h is None:   # a prefill chunk; the request is not finished yet
                    out.append(None)
                    continue
                if not bool(ids.any()):
                    # vLLM's start-up profile run: all-zero dummy tokens, no prompt. It
                    # sizes memory from this output, so it gets one of the real size.
                    # A real prompt without its markers still fails in Positions.
                    out.append(torch.zeros(L.PACKED + TRAILER, device=h.device))
                    continue
                pos = Positions(ids, m.pointer_token_ids)
                v = m.pointer_heads.decide(h, pos, m.language_model.lm_head.weight)
                out.append(torch.cat([v, torch.tensor([float(pos.per_moment), float(pos.n_moments)],
                                                      device=v.device)]))
            return out

    @default_pooling_type(seq_pooling_type="ALL", tok_pooling_type="ALL")
    @MULTIMODAL_REGISTRY.register_processor(Qwen3VLMultiModalProcessor, info=Qwen3_5ProcessingInfo,
                                            dummy_inputs=Qwen3VLDummyInputsBuilder)
    class PointerQwen3_5(Qwen3_5ForConditionalGeneration):
        is_pooling_model = True

        def __init__(self, *, vllm_config, prefix: str = "model"):
            super().__init__(vllm_config=vllm_config, prefix=prefix)
            cfg = vllm_config.model_config.hf_config
            meta = cfg.pointer
            if int(meta["packed"]) != L.PACKED:
                raise ValueError(f"checkpoint packs {meta['packed']} values, this client {L.PACKED}: "
                                 "the checkpoint was exported by a different pointer layout")
            self.pointer_token_ids = {k: int(v) for k, v in meta["token_ids"].items()}
            self.pointer_heads = Heads(cfg.text_config.hidden_size).float()
            self.pooler = PointerPooler(self)

    return PointerQwen3_5


def __getattr__(name):
    # vLLM resolves "module:PointerQwen3_5" lazily; build the class on first use so
    # importing this module (for `register`) never imports vLLM's model code.
    if name == "PointerQwen3_5":
        cls = _model_class()
        globals()[name] = cls
        return cls
    raise AttributeError(name)


#: Values the pooler appends after the layout's packed vector: vision tokens per
#: moment, and moments. The caller checks them against the board it sent.
TRAILER = 2
