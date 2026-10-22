# Third-party notices

Vision retrieves these independent projects and model assets when a user runs setup. Their licenses apply to those components and remain separate from Vision's source.

## Hermes Agent

Hermes Agent is downloaded from [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) by its official Windows installer. The upstream project is MIT licensed; its copyright and license files are included in the local Hermes checkout under `runtime/hermes/hermes-agent/` after setup.

## Kokoro speech synthesis

`kokoro-onnx` supplies the ONNX runtime and model export. The project is MIT licensed; see [its license](https://github.com/thewh1teagle/kokoro-onnx/blob/main/LICENSE). The Kokoro-82M model weights are licensed under Apache-2.0; see the [model card](https://huggingface.co/hexgrad/Kokoro-82M).

## Other downloaded components

Electron and the Python packages in `backend/requirements.txt` are distributed under their respective upstream licenses. Their package metadata and license files are installed on the user's computer, not copied into this repository.
