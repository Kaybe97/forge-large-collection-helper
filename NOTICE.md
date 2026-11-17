# Notices and attribution

**Forge Large Collection Helper** is an independent, unofficial extension for [Stable Diffusion WebUI Forge Neo](https://github.com/Haoming02/sd-webui-forge-classic/tree/neo). It is not affiliated with or endorsed by the Forge Neo maintainers.

## Development disclosure

All code newly written for this extension was AI-generated using OpenAI ChatGPT. That statement excludes any code or implementation details adapted from other projects.

## Upstream references

The extension was developed against Forge Neo's built-in **Extra Networks** implementation, particularly `modules/ui_extra_networks.py`, its JavaScript UI controls and its HTML/CSS conventions. It calls Forge's native card renderer at runtime, replaces selected methods at runtime, and follows its existing element names and callbacks. The Forge Neo source tree and third-party dependencies are **not** included in this distribution.

- Forge Neo: https://github.com/Haoming02/sd-webui-forge-classic/tree/neo
- Original Stable Diffusion WebUI Forge: https://github.com/lllyasviel/stable-diffusion-webui-forge
- AUTOMATIC1111 Stable Diffusion WebUI: https://github.com/AUTOMATIC1111/stable-diffusion-webui

Upstream projects retain their respective copyrights and licenses. See each upstream repository for its terms and notices. This distribution does not contain image-generation model weights or LoRA files.
