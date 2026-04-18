---
name: wechat-clawbot-media-send
description: Send local images, videos, and files to WeChat/Weixin via Hermes MEDIA paths.
version: 1.1.0
author: Hermes Agent
license: MIT
---

# WeChat ClawBot Media Send

Use when a user wants a local image, video, or file delivered in WeChat.

## Rule

Make sure the local file already exists, then put this in the final reply:
`MEDIA:/absolute/path/to/file`

## Note

If sending does not work, check the WeChat ClawBot/OpenClaw Weixin docs:
https://github.com/Tencent/openclaw-weixin
