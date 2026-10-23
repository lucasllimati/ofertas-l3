from datetime import timedelta

from src.approval import keyboard, process_updates, send_previews, sign_callback, verify_callback
from src.common.telegram import FakeTelegram
from src.common.util import parse_iso, slot_to_utc
from src.pipeline.content import create_content
from src.pipeline.ingest import ingest
from src.pipeline.score import score_niche
from src.pipeline.transform import transform
from src.publishers.telegram import CIRCUIT_BREAKER_FAILURES, publish_niche
from tests.conftest import ADMIN_ID, DAY1

TZ = "America/Sao_Paulo"


def prepare(ctx, niche_id="casa"):
    niche = ctx.config.niche(niche_id)
    ingest(ctx, niche)
    transform(ctx, niche)
    score_niche(ctx, niche)
    create_content(ctx, niche)
    send_previews(ctx, niche)
    return niche


def items(db, niche="casa"):
    return db.fetchall("SELECT * FROM content_item WHERE niche_id = ? ORDER BY scheduled_for, id", (niche,))


def click(ctx, action, content_id, user_id=ADMIN_ID):
    ctx.telegram.push_callback(sign_callback(ctx.hmac_secret, action, content_id), 1, ctx.admin_chat_id, user_id)


# ------------------------------------------------------------------- assinatura
def test_callback_signature_roundtrip_and_tamper():
    data = sign_callback("s3cret", "a", "abc123")
    assert len(data.encode()) <= 64
    assert verify_callback("s3cret", data) == ("a", "abc123")
    assert verify_callback("other", data) is None
    assert verify_callback("s3cret", data.replace("abc123", "zzz999")) is None
    assert verify_callback("s3cret", "x:abc:123") is None
    assert verify_callback("", data) is None
    kb = keyboard("s3cret", "abc123")
    assert [b["text"][0] for b in kb["inline_keyboard"][0]] == ["✅", "❌", "⏭"]


# ---------------------------------------------------------------------- prévias
def test_previews_go_to_admin_with_buttons(make_ctx, db):
    ctx = make_ctx()
    prepare(ctx)
    previews = [m for m in ctx.telegram.sent if m["chat_id"] == "admin-chat"]
    assert len(previews) == 5
    assert all(m["reply_markup"] for m in previews)
    assert {i["status"] for i in items(db)} == {"pending_approval"}
    assert all(i["media_file_id"] for i in items(db))
    send_previews(ctx, ctx.config.niche("casa"))  # reexecução não reenvia
    assert len([m for m in ctx.telegram.sent if m["chat_id"] == "admin-chat"]) == 5


def test_auto_approve_above_score(make_ctx, db, config):
    niche = config.niche("casa")
    niche.settings.approval = "auto_above_score"
    niche.settings.auto_approve_min_score = 0.0
    ctx = make_ctx()
    prepare(ctx)
    assert {i["status"] for i in items(db)} == {"approved"}
    assert db.scalar("SELECT count(*) FROM audit_log WHERE action = 'auto_approve'") == 5


# -------------------------------------------------------------------- aprovação
def test_approve_reject_reschedule(make_ctx, db):
    ctx = make_ctx()
    prepare(ctx)
    first, second, third = items(db)[:3]
    click(ctx, "a", first["id"])
    click(ctx, "r", second["id"])
    click(ctx, "s", third["id"])
    assert process_updates(ctx)["callbacks"] == 3
    by_id = {i["id"]: i for i in items(db)}
    assert by_id[first["id"]]["status"] == "approved"
    assert by_id[second["id"]]["status"] == "rejected"
    assert by_id[third["id"]]["status"] == "approved"
    assert by_id[third["id"]]["scheduled_for"] > third["scheduled_for"]
    assert db.scalar("SELECT count(*) FROM audit_log WHERE action LIKE 'callback_%'") == 3
    # offset persistido: a segunda leitura não reprocessa
    assert process_updates(ctx)["callbacks"] == 0


def test_unauthorized_user_and_forged_signature_are_ignored(make_ctx, db):
    ctx = make_ctx()
    prepare(ctx)
    target = items(db)[0]
    click(ctx, "a", target["id"], user_id=999)
    ctx.telegram.push_callback(f"a:{target['id']}:0000000000000000", 1, "admin-chat", ADMIN_ID)
    process_updates(ctx)
    assert items(db)[0]["status"] == "pending_approval"
    actions = {r["action"] for r in db.fetchall("SELECT action FROM audit_log")}
    assert {"unauthorized_callback", "invalid_signature"} <= actions


def test_old_preview_expires_instead_of_approving(make_ctx, db):
    ctx = make_ctx()
    prepare(ctx)
    target = items(db)[0]
    later = make_ctx(now=ctx.now + timedelta(hours=80), telegram=ctx.telegram)
    click(later, "a", target["id"])
    process_updates(later)
    assert items(db)[0]["status"] == "expired"


def test_commands_pause_and_resume(make_ctx, db):
    ctx = make_ctx()
    ctx.telegram.push_command("/pausar casa telegram", "admin-chat")
    ctx.telegram.push_command("/status", "admin-chat")
    ctx.telegram.push_command("/pausar casa telegram", "admin-chat", user_id=999)  # não autorizado
    process_updates(ctx)
    assert db.scalar("SELECT paused FROM channel_state WHERE niche_id = 'casa'") == 1
    replies = [m["text"] for m in ctx.telegram.sent if m["kind"] == "message"]
    assert any("Pausado" in r for r in replies) and any("Status" in r for r in replies)
    ctx.telegram.push_command("/retomar casa telegram", "admin-chat")
    process_updates(ctx)
    assert db.scalar("SELECT paused FROM channel_state WHERE niche_id = 'casa'") == 0


# ------------------------------------------------------------------- publicação
def approve_all(ctx, db):
    for i in items(db):
        click(ctx, "a", i["id"])
    process_updates(ctx)


def test_publish_only_due_items_without_duplicates(make_ctx, db):
    ctx = make_ctx()
    prepare(ctx)
    approve_all(ctx, db)
    noon = make_ctx(now=slot_to_utc(DAY1, "12:30", TZ), telegram=ctx.telegram)
    result = publish_niche(noon, noon.config.niche("casa"))
    due = [i for i in items(db) if parse_iso(i["scheduled_for"]) <= noon.now]
    assert result["published"] == len(due) > 0
    again = publish_niche(noon, noon.config.niche("casa"))
    assert again["published"] == 0  # reexecução não duplica
    channel_posts = [m for m in ctx.telegram.sent if m["chat_id"] == "@chan_casa"]
    assert len(channel_posts) == len(due)
    assert all(m["photo_ref"].startswith("file-") for m in channel_posts)  # reaproveita a mídia da prévia
    assert all("#publi" in m["caption"] for m in channel_posts)


def test_daily_limit_respected(make_ctx, db, config):
    config.niche("casa").settings.limits.posts_per_day.telegram = 2
    ctx = make_ctx()
    prepare(ctx)
    approve_all(ctx, db)
    night = make_ctx(now=slot_to_utc(DAY1, "23:00", TZ), telegram=ctx.telegram)
    assert publish_niche(night, night.config.niche("casa"))["published"] == 2
    assert publish_niche(night, night.config.niche("casa"))["published"] == 0


def test_circuit_breaker_pauses_channel(make_ctx, db):
    ctx = make_ctx()
    prepare(ctx)
    approve_all(ctx, db)
    ctx.telegram.fail_chats.add("@chan_casa")
    night = make_ctx(now=slot_to_utc(DAY1, "23:00", TZ), telegram=ctx.telegram)
    publish_niche(night, night.config.niche("casa"))
    state = db.fetchone("SELECT * FROM channel_state WHERE niche_id = 'casa'")
    assert state["paused"] == 1 and state["consecutive_failures"] == CIRCUIT_BREAKER_FAILURES
    assert {i["status"] for i in items(db)} == {"approved"}  # nada perdido, volta para a fila
    assert any("pausado" in m.get("text", "") for m in ctx.telegram.sent)
    assert publish_niche(night, night.config.niche("casa")).get("paused") == 1


def test_ambiguous_failure_is_not_retried(make_ctx, db):
    class Flaky(FakeTelegram):
        def send_photo(self, chat_id, photo, caption, reply_markup=None):
            if chat_id == "@chan_casa":
                raise ConnectionError("timeout")
            return super().send_photo(chat_id, photo, caption, reply_markup)

    ctx = make_ctx(telegram=Flaky(admin_user_id=ADMIN_ID))
    prepare(ctx)
    approve_all(ctx, db)
    night = make_ctx(now=slot_to_utc(DAY1, "23:00", TZ), telegram=ctx.telegram)
    publish_niche(night, night.config.niche("casa"))
    assert "publish_unknown" in {i["status"] for i in items(db)}
    before = db.scalar("SELECT count(*) FROM content_item WHERE status = 'publish_unknown'")
    publish_niche(night, night.config.niche("casa"))
    assert db.scalar("SELECT count(*) FROM content_item WHERE status = 'publish_unknown'") >= before


def test_stale_approved_items_expire(make_ctx, db):
    ctx = make_ctx()
    prepare(ctx)
    approve_all(ctx, db)
    later = make_ctx(run_date=DAY1 + timedelta(days=3), now=ctx.now + timedelta(days=3), telegram=ctx.telegram)
    assert publish_niche(later, later.config.niche("casa"))["expired"] == 5
