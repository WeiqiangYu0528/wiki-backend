# Media and Voice Stack

## Overview

OpenClaw's media and voice stack covers four distinct capability areas: **media understanding** (attaching images, audio, video, and documents to agent context), **media generation** (image, music, video synthesis), **speech/TTS** (text-to-speech synthesis for voice notes and telephony), and **realtime voice** (bidirectional live voice bridges using WebRTC/WebSocket audio). All four areas follow the same plugin extension model: providers are registered via the plugin API, and the agent runtime selects providers based on configuration.

The media layer handles MIME detection, codec transcoding (via `ffmpeg`), format normalization, file-based inbound roots, base64 encoding, and audio metadata. It acts as the shared I/O foundation that TTS, realtime voice, and media understanding all depend on. The `src/media/mime.ts` map covers ~30 MIME types across image (HEIC, JPEG, PNG, WebP, GIF), audio (Opus, OGG, MP3, WAV, FLAC, AAC, M4A), video (MP4, MOV), and document (PDF, JSON, ZIP) formats.

## Key Types

### Realtime Voice

```ts
// src/realtime-voice/provider-types.ts
export type RealtimeVoiceBridgeCallbacks = {
  onAudio: (muLaw: Buffer) => void;     // receive audio from bridge
  onClearAudio: () => void;             // clear audio buffer
  onMark?: (markName: string) => void;  // media timestamp mark
  onTranscript?: (role, text, isFinal) => void;
  onToolCall?: (event: RealtimeVoiceToolCallEvent) => void;
  onReady?: () => void;
  onError?: (error: Error) => void;
  onClose?: (reason: "completed" | "error") => void;
};

export type RealtimeVoiceBridge = {
  connect(): Promise<void>;
  sendAudio(audio: Buffer): void;       // send mu-law audio to provider
  setMediaTimestamp(ts: number): void;
  sendUserMessage?(text: string): void; // inject text turn
};
```

Tools registered with the voice bridge follow the same JSON schema function contract as agent tools (`RealtimeVoiceTool`), enabling the model to call agent tools during a voice session.

### TTS / Speech

```ts
// src/tts/provider-types.ts
export type SpeechProviderId = string;
export type SpeechSynthesisTarget = "audio-file" | "voice-note";

export type TtsDirectiveParseResult = {
  cleanedText: string;
  ttsText?: string;       // override text for synthesis
  hasDirective: boolean;
  overrides: TtsDirectiveOverrides;
  warnings: string[];
};

export type SpeechModelOverridePolicy = {
  enabled: boolean;
  allowText: boolean;
  allowProvider: boolean;
  allowVoice: boolean;
  allowModelId: boolean;
  allowVoiceSettings: boolean;
  // ...
};
```

TTS directives allow inline overrides embedded in the assistant's reply text (e.g., different voice, provider, or speed for a specific segment).

### Media Understanding

```ts
// Conceptual shape from src/media-understanding/types.ts
export type MediaUnderstandingProvider = {
  id: string;
  understand(request: MediaUnderstandingRequest): Promise<MediaUnderstandingResult>;
};
```

Media understanding providers accept images, audio, and video and return structured descriptions that the agent can use as context.

## Architecture

### Media I/O Layer (`src/media/`)

The media module handles low-level file operations:
- `mime.ts` — `detectMime(buffer)` using `file-type` library for magic byte detection
- `audio.ts`, `audio-tags.ts` — audio metadata reading, format normalization
- `ffmpeg-exec.ts` — executes `ffmpeg` for format conversion; `ffmpeg-limits.ts` caps processing time/size
- `channel-inbound-roots.ts` — maps inbound media from channels to file system roots for safe access
- `file-context.ts` — resolves media file paths for agent context injection
- `base64.ts` — encodes/decodes media for API payloads

### TTS Pipeline

1. Agent produces reply text with optional embedded TTS directives.
2. `parseTtsDirective()` extracts `ttsText` override and `TtsDirectiveOverrides`.
3. Active TTS provider's `synthesize()` method generates audio bytes.
4. Audio is delivered via the channel's outbound adapter (as voice note or telephony audio).
5. `SpeechModelOverridePolicy` gates which fields callers can override.

### Realtime Voice Pipeline

1. A channel adapter with voice capability opens a `RealtimeVoiceBridge` via the active realtime voice provider.
2. The bridge establishes a WebSocket/WebRTC session with the provider.
3. Inbound audio (`onAudio`) is streamed to the bridge; the provider transcribes and generates text + audio output.
4. `onToolCall` fires when the model invokes a registered tool during the session.
5. `onTranscript` delivers incremental and final transcription to the session.
6. Bridge teardown via `close()` emits `onClose` with `"completed"` or `"error"`.

### Realtime Transcription

A separate `RealtimeTranscriptionProvider` handles one-way audio-to-text (without model response generation). This is used for voice message transcription rather than interactive voice.

### Generation Providers

Image, music, and video generation follow the same plugin provider pattern:
- `ImageGenerationProvider` — `generate(request)` → image bytes/URL
- `MusicGenerationProvider` — `generate(request)` → audio bytes/URL
- `VideoGenerationProvider` — `generate(request)` → video bytes/URL

Providers register via `api.registerImageGenerationProvider()`, `api.registerMusicGenerationProvider()`, etc. in the plugin API.

### Media Understanding via Channel Inbound

When a user sends a photo, audio, or video to a channel, the channel adapter passes the media through `channel-inbound-roots.ts` which:
1. Resolves a safe filesystem root for the inbound media.
2. Writes the file to a temp path.
3. Returns a `FileContext` that the agent runtime can attach to its context window.

MIME detection ensures the agent receives the correct type annotation (e.g., `image/jpeg` vs. `image/heic`).

## Source Files

| File | Purpose |
|------|---------|
| `src/media/mime.ts` | `detectMime()` — magic byte MIME detection; MIME-to-extension map |
| `src/media/audio.ts` | Audio metadata reading and normalization |
| `src/media/ffmpeg-exec.ts` | `ffmpeg` execution for format conversion |
| `src/media/ffmpeg-limits.ts` | Size/time limits for ffmpeg processing |
| `src/media/channel-inbound-roots.ts` | Safe inbound media file root resolution |
| `src/media/file-context.ts` | Media file path resolution for agent context |
| `src/media/base64.ts` | Media encoding for API payloads |
| `src/tts/provider-types.ts` | `SpeechProviderId`, `TtsDirectiveParseResult`, `SpeechModelOverridePolicy` |
| `src/tts/provider-registry.ts` | TTS provider registration and lookup |
| `src/realtime-voice/provider-types.ts` | `RealtimeVoiceBridge`, `RealtimeVoiceBridgeCallbacks`, `RealtimeVoiceTool` |
| `src/realtime-voice/provider-registry.ts` | Realtime voice provider registry |
| `src/realtime-transcription/provider-types.ts` | One-way transcription provider types |
| `src/media-understanding/types.ts` | `MediaUnderstandingProvider` interface |
| `src/image-generation/types.ts` | `ImageGenerationProvider` interface |
| `src/music-generation/types.ts` | `MusicGenerationProvider` interface |
| `src/video-generation/types.ts` | `VideoGenerationProvider` interface |

## See Also

- [Plugin Platform](plugin-platform.md) — providers register via the plugin API
- [Channel Plugin Adapters](channel-plugin-adapters.md) — channel adapters deliver inbound media and dispatch TTS output
- [Node Host and Device Pairing](node-host-and-device-pairing.md) — node host runs ffmpeg and native audio capabilities
- [Canvas and Control UI](canvas-and-control-ui.md) — canvas surfaces media generation output
- [Canvas Voice and Device Control Loop](../syntheses/canvas-voice-and-device-control-loop.md)
- [Device Augmented Agent Architecture](../concepts/device-augmented-agent-architecture.md)
