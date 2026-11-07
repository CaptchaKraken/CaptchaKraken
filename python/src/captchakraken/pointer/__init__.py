"""The pointer solver: a captcha answered from ONE forward pass, never generated.

The board is shown to a Qwen3.5 model (still, or a video), optionally with the
element detector's findings drawn over it as thin numbered outlines and listed
in the prompt. Every question the answer needs (which action, how many clicks,
where each one lands, what to type, which moment of a video) has a marker
token in the prompt, and small heads read each marker's hidden state from the
prefill. The answer always carries points; it carries an element's number too
when the point lands on a numbered element.

  layout    the prompt, the questions and the packed decision vector
  elements  detector output -> numbered elements, and the element under a point
  marks     the outlines and numbers drawn on the board
  heads     the torch heads (training and serving share them)
  detector  the element detector (Mask R-CNN, ResNet-18 FPN)
  vllm_plugin  the heads inside vLLM's pooling runner
  service   board in, answer out: detector, marks, vLLM, decode

Only `layout`, `elements` and `marks` import without torch.
"""
