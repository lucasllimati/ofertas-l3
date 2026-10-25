"""Cliente mínimo da Bot API do Telegram + fake para demo/testes."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

from src.common.logging import redact


class TelegramError(RuntimeError):
    """A API respondeu com erro: a mensagem com certeza NÃO foi entregue."""

    def __init__(self, method: str, description: str, code: int | None = None):
        super().__init__(f"telegram {method}: {description}")
        self.code = code


class TelegramClient:
    def __init__(self, token: str, http: httpx.Client | None = None, sleep=time.sleep):
        self._token = token
        self.http = http or httpx.Client(timeout=40)
        self._sleep = sleep

    def _call(self, method: str, data: dict[str, Any] | None = None, files=None) -> Any:
        url = f"https://api.telegram.org/bot{self._token}/{method}"
        payload = {k: v for k, v in (data or {}).items() if v is not None}
        for attempt in range(3):
            try:
                if files:
                    form = {k: json.dumps(v) if isinstance(v, (dict, list)) else str(v) for k, v in payload.items()}
                    resp = self.http.post(url, data=form, files=files)
                else:
                    resp = self.http.post(url, json=payload)
            except httpx.HTTPError as exc:
                # Nunca propaga a exceção original: a URL contém o token.
                raise ConnectionError(redact(f"telegram {method}: {type(exc).__name__}", [self._token])) from None
            try:
                body = resp.json() if resp.content else {}
            except ValueError:
                # Página de erro do gateway (ex.: 502 em HTML): não dá para saber se a mensagem saiu.
                raise ConnectionError(f"telegram {method}: resposta inválida HTTP {resp.status_code}") from None
            if body.get("ok"):
                return body.get("result")
            retry_after = (body.get("parameters") or {}).get("retry_after")
            if resp.status_code == 429 and retry_after and attempt < 2:
                self._sleep(min(int(retry_after), 30))
                continue
            raise TelegramError(
                method,
                redact(str(body.get("description", resp.status_code)), [self._token]),
                body.get("error_code"),
            )
        raise TelegramError(method, "tentativas esgotadas")

    def get_me(self) -> dict[str, Any]:
        return self._call("getMe")

    def send_message(self, chat_id: str, text: str, reply_markup=None, parse_mode="HTML") -> dict:
        return self._call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text[:4096],
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
                "link_preview_options": {"is_disabled": True},
            },
        )

    def send_photo(self, chat_id: str, photo: bytes | str, caption: str, reply_markup=None) -> dict:
        data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML", "reply_markup": reply_markup}
        if isinstance(photo, bytes):
            return self._call("sendPhoto", data, files={"photo": ("post.png", photo, "image/png")})
        return self._call("sendPhoto", {**data, "photo": photo})

    def get_chat_member(self, chat_id: str, user_id: int) -> dict[str, Any]:
        return self._call("getChatMember", {"chat_id": chat_id, "user_id": user_id})

    def send_document(self, chat_id: str, filename: str, content: bytes, caption: str = "") -> dict:
        data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
        return self._call("sendDocument", data, files={"document": (filename, content, "text/csv")})

    def edit_reply_markup(self, chat_id: str, message_id: str, reply_markup) -> Any:
        return self._call(
            "editMessageReplyMarkup",
            {"chat_id": chat_id, "message_id": int(message_id), "reply_markup": reply_markup},
        )

    def answer_callback(self, callback_id: str, text: str) -> Any:
        return self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    def get_updates(self, offset: int | None) -> list[dict[str, Any]]:
        return self._call(
            "getUpdates",
            {"offset": offset, "timeout": 0, "allowed_updates": ["message", "callback_query"]},
        )


def largest_photo_id(message: dict[str, Any]) -> str | None:
    photos = message.get("photo") or []
    return photos[-1]["file_id"] if photos else None


class FakeTelegram:
    """Guarda tudo em memória (e opcionalmente em out/). Com auto_approve, cada prévia
    enviada ao chat de admin gera um clique em "Aprovar" no próximo get_updates."""

    def __init__(self, outbox: Path | None = None, admin_user_id: int = 1, auto_approve: bool = False):
        self.sent: list[dict[str, Any]] = []
        self.pending_updates: list[dict[str, Any]] = []
        self.outbox = outbox
        self.admin_user_id = admin_user_id
        self.auto_approve = auto_approve
        self.fail_chats: set[str] = set()  # chats que respondem erro da API (testes)
        self.not_admin_chats: set[str] = set()  # canais onde o bot não é admin (testes)
        self._msg_id = 100
        self._update_id = int(time.time() * 1000)  # monotônico entre execuções, como no Telegram
        if outbox:
            outbox.mkdir(parents=True, exist_ok=True)

    def _record(self, kind: str, chat_id: str, **data) -> dict[str, Any]:
        if str(chat_id) in self.fail_chats:
            raise TelegramError(kind, "Bad Request: chat not found", 400)
        self._msg_id += 1
        entry = {"kind": kind, "chat_id": str(chat_id), "message_id": self._msg_id, **data}
        self.sent.append(entry)
        if self.outbox:
            with open(self.outbox / "telegram_outbox.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps({k: v for k, v in entry.items() if k != "photo_bytes"}, ensure_ascii=False) + "\n")
        message = {"message_id": self._msg_id, "chat": {"id": chat_id}}
        if kind == "photo":
            message["photo"] = [{"file_id": f"file-{self._msg_id}"}]
        return message

    def get_me(self) -> dict[str, Any]:
        return {"id": 42, "username": "garimpo_demo_bot"}

    def send_message(self, chat_id, text, reply_markup=None, parse_mode="HTML"):
        return self._record("message", chat_id, text=text, reply_markup=reply_markup)

    def send_photo(self, chat_id, photo, caption, reply_markup=None):
        msg = self._record(
            "photo",
            chat_id,
            caption=caption,
            reply_markup=reply_markup,
            photo_ref=photo if isinstance(photo, str) else f"<{len(photo)} bytes>",
        )
        if self.auto_approve and reply_markup:
            data = reply_markup["inline_keyboard"][0][0]["callback_data"]
            self.push_callback(data, msg["message_id"], chat_id)
        return msg

    def send_document(self, chat_id, filename, content, caption=""):
        return self._record("document", chat_id, filename=filename, caption=caption, size=len(content))

    def get_chat_member(self, chat_id, user_id):
        if str(chat_id) in self.fail_chats:
            raise TelegramError("getChatMember", "Bad Request: chat not found", 400)
        if str(chat_id) in self.not_admin_chats:
            return {"status": "member"}
        return {"status": "administrator", "can_post_messages": True}

    def edit_reply_markup(self, chat_id, message_id, reply_markup):
        self.sent.append({"kind": "edit", "chat_id": str(chat_id), "message_id": message_id})
        return True

    def answer_callback(self, callback_id, text):
        return True

    def push_callback(self, data: str, message_id: int, chat_id, user_id: int | None = None) -> None:
        self._update_id += 1
        self.pending_updates.append(
            {
                "update_id": self._update_id,
                "callback_query": {
                    "id": f"cb{self._update_id}",
                    "from": {"id": user_id if user_id is not None else self.admin_user_id},
                    "data": data,
                    "message": {"message_id": message_id, "chat": {"id": chat_id}},
                },
            }
        )

    def push_command(self, text: str, chat_id, user_id: int | None = None) -> None:
        self._update_id += 1
        self.pending_updates.append(
            {
                "update_id": self._update_id,
                "message": {
                    "message_id": 1,
                    "text": text,
                    "chat": {"id": chat_id},
                    "from": {"id": user_id if user_id is not None else self.admin_user_id},
                },
            }
        )

    def get_updates(self, offset):
        return [u for u in self.pending_updates if offset is None or u["update_id"] >= offset]
