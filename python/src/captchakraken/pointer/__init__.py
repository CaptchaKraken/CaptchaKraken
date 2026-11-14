"""The pointer solver: a captcha answered from ONE forward pass, never generated.

The board is shown to a Qwen3.5 model (still, or a video) as it was captured.
Every question the answer needs (which action, how many clicks,
where each one lands, what to type, which moment of a video) has a marker
token in the prompt, and small heads read each marker's hidden state from the
prefill. The answer always carries points.

  layout    the prompt, the questions and the packed decision vector
  elements  numbered elements, and the element under a point (training reads
            them; the client sends every board bare)
  marks     the outlines and numbers a marked training board is drawn with
  heads     the torch heads (training and serving share them)
  vllm_plugin  the heads inside vLLM's pooling runner
  service   board in, answer out: vLLM, decode

Only `layout`, `elements` and `marks` import without torch.
"""
