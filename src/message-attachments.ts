import type { PagerMessage } from "./pager-client.js";

export type MessageAttachment = NonNullable<PagerMessage["attachments"]>[number];

const POSITIVE_EMOJI_ONLY = /^[\s👍👌✅🔥❤️🙏😊🙂💯👏]+$/u;

export function isMessengerReactionAttachment(
  attachments?: MessageAttachment[] | null,
): boolean {
  for (const attachment of attachments ?? []) {
    const type = (attachment.type ?? "").toLowerCase();
    if (
      ["sticker", "like", "thumbs_up", "emoji", "fallback", "reaction"].includes(type)
    ) {
      return true;
    }
    if (type === "image") {
      const payload = attachment.payload ?? {};
      if (payload.sticker_id || attachment.sticker_id) {
        return true;
      }
      const url = (payload.url ?? "").toLowerCase();
      if (
        [
          "sticker",
          "/t39.1997",
          "reaction",
          "like_thumb",
          "thumbs",
          "emoji.php",
          "/images/emoji",
          "static.xx.fbcdn.net/images/emoji",
        ].some((marker) => url.includes(marker))
      ) {
        return true;
      }
      const width = payload.width ?? attachment.width;
      const height = payload.height ?? attachment.height;
      if (width && height) {
        const w = Number(width);
        const h = Number(height);
        if (Number.isFinite(w) && Number.isFinite(h) && w <= 200 && h <= 200) {
          return true;
        }
      }
    }
  }
  return false;
}

export function isPositiveMessageReaction(reaction?: string | null): boolean {
  if (!reaction?.trim()) {
    return false;
  }
  const normalized = reaction.trim().toLowerCase();
  if (["like", "love", "care"].includes(normalized)) {
    return true;
  }
  return POSITIVE_EMOJI_ONLY.test(reaction.trim());
}

export function isReactionOnlyMessage(
  text: string,
  attachments?: MessageAttachment[] | null,
  messageReaction?: string | null,
): boolean {
  const trimmed = (text || "").trim();
  if (trimmed && POSITIVE_EMOJI_ONLY.test(trimmed) && trimmed.length <= 8) {
    return true;
  }
  if (!trimmed && isMessengerReactionAttachment(attachments)) {
    return true;
  }
  if (!trimmed && isPositiveMessageReaction(messageReaction)) {
    return true;
  }
  return false;
}

export function extractProofImageUrl(message: PagerMessage): string | undefined {
  if (isReactionOnlyMessage(message.text ?? "", message.attachments, message.reaction)) {
    return undefined;
  }
  for (const attachment of message.attachments ?? []) {
    if (attachment.type === "image" && !isMessengerReactionAttachment([attachment])) {
      const url = attachment.payload?.url;
      if (url) {
        return url;
      }
    }
  }
  return undefined;
}

export function resolveMessageReaction(message: PagerMessage): string | undefined {
  if (message.reaction?.trim()) {
    return message.reaction.trim();
  }
  if (isReactionOnlyMessage(message.text ?? "", message.attachments)) {
    return "like";
  }
  return undefined;
}
