# Third-party notices

Vision retrieves these independent projects and model assets when a user runs setup. Their licenses apply to those components and remain separate from Vision's source.

## Hermes Agent

Setup reuses an existing Hermes Agent installation when available. If Hermes is absent, setup downloads and runs the official Windows installer from [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent). The upstream project is MIT licensed; its copyright and license files are available in the local Hermes checkout after installation.

## Kokoro speech synthesis

`kokoro-onnx` supplies the ONNX runtime and model export. The project is MIT licensed; see [its license](https://github.com/thewh1teagle/kokoro-onnx/blob/main/LICENSE). The Kokoro-82M model weights are licensed under Apache-2.0; see the [model card](https://huggingface.co/hexgrad/Kokoro-82M).

## Other downloaded components

Electron and the Python packages in `backend/requirements.txt` are distributed under their respective upstream licenses. Their package metadata and license files are installed on the user's computer, not copied into this repository.
