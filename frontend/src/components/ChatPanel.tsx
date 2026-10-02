import { useEffect, useRef, useState } from "react";
import type { RideMessageOut } from "../api/rides";

interface ChatPanelProps {
  open: boolean;
  onClose: () => void;
  messages: RideMessageOut[];
  myUserId: number;
  otherPartyName?: string;
  onSend: (text: string) => void;
  sending: boolean;
}

export default function ChatPanel({
  open,
  onClose,
  messages,
  myUserId,
  otherPartyName,
  onSend,
  sending,
}: ChatPanelProps) {
  const [text, setText] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) bottomRef.current?.scrollIntoView({ block: "end" });
  }, [open, messages.length]);

  if (!open) return null;

  function handleSend() {
    const trimmed = text.trim();
    if (!trimmed || sending) return;
    onSend(trimmed);
    setText("");
  }

  return (
    <div className="fixed inset-0 z-30 flex flex-col bg-[#20241f]">
      <div className="flex items-center gap-3 px-4 pt-6 pb-4 border-b border-white/10">
        <button
          onClick={onClose}
          className="w-9 h-9 rounded-full bg-white/10 flex items-center justify-center text-white"
          aria-label="Close chat"
        >
          <i className="fa-solid fa-arrow-left" />
        </button>
        <div>
          <h1 className="text-white text-lg font-extrabold leading-tight">
            {otherPartyName || "Chat"}
          </h1>
          <p className="text-slate-400 text-xs">In-ride messages</p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-2">
        {messages.length === 0 && (
          <p className="text-slate-400 text-sm text-center mt-6">
            No messages yet. Say hello.
          </p>
        )}
        {messages.map((m) => {
          const mine = m.sender_id === myUserId;
          return (
            <div key={m.id} className={`flex ${mine ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[75%] rounded-2xl px-4 py-2.5 text-sm ${
                  mine
                    ? "bg-[#1be451] text-neutral-900 font-medium"
                    : "bg-white/10 text-slate-100"
                }`}
              >
                <p>{m.text}</p>
                <p className={`text-[10px] mt-1 ${mine ? "text-neutral-900/60" : "text-slate-400"}`}>
                  {new Date(m.created_at).toLocaleTimeString(undefined, {
                    hour: "numeric", minute: "2-digit",
                  })}
                </p>
              </div>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      <div className="flex items-center gap-2 px-4 py-4 border-t border-white/10">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSend();
          }}
          placeholder="Type a message…"
          className="flex-1 rounded-full px-4 py-3 bg-white/10 border border-white/20 text-white placeholder:text-slate-400"
        />
        <button
          onClick={handleSend}
          disabled={sending || !text.trim()}
          className="w-12 h-12 rounded-full bg-[#1be451] text-neutral-900 flex items-center justify-center disabled:opacity-50"
          aria-label="Send"
        >
          <i className="fa-solid fa-paper-plane" />
        </button>
      </div>
    </div>
  );
}
