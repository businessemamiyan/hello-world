"""پروژه‌های کاربر (مثلاً VQ ERP، VQ Factory، NovaTunnel): کارت خلاصه + کارهای باز + یادداشت‌های پیشرفت + مستندات کامل (قابل‌جست‌وجو).

مهرداد از طریق چکیدهٔ زمینه (prompt) همیشه در جریان وضعیت هر پروژه است؛ هر چه کاربر دربارهٔ پیشرفت/مشکل/کار تازه بگوید با
«project_op» ثبت می‌شود. داده‌ها فقط در دیتابیس خود سرور است (نه در کد/گیت): با
    python -m app.projects /data/projects_import
از یک پوشه (هر پروژه: <id>.json + اختیاری <id>.md) وارد می‌شوند.
"""
import json
import os
import re
import sys

from . import life
from .memory import normalize_fa

STATUS_MAX = 40
_H = re.compile(r"^(#{2,3})\s+(.*)$")


def chunk_markdown(md, max_chars=5000):
    """مارک‌داون → [(عنوان بخش, متن)]. بخش‌های ## جدا؛ بخش بزرگ‌تر از max_chars اول با ### بعد با پاراگراف شکسته می‌شود."""
    sections, title, buf, sub = [], "مقدمه", [], None
    def flush():
        body = "\n".join(buf).strip()
        if body:
            sections.append((title if not sub else f"{title} — {sub}", body))
    for line in (md or "").splitlines():
        m = _H.match(line)
        if m and len(m.group(1)) == 2:
            flush(); title, buf, sub = m.group(2).strip(), [], None
        elif m and len(m.group(1)) == 3:
            flush(); sub, buf = m.group(2).strip(), []
        else:
            buf.append(line)
    flush()
    out = []
    for t, body in sections:
        if t.strip() in ("فهرست", "فهرست مطالب"):          # فهرست پیوندی فقط نویز جست‌وجو است
            continue
        if len(body) <= max_chars:
            out.append((t, body))
            continue
        part, n = "", 1
        for para in re.split(r"\n\s*\n", body):
            if part and len(part) + len(para) > max_chars:
                out.append((f"{t} ({life.fa(n)})", part.strip())); part, n = "", n + 1
            part += para + "\n\n"
        if part.strip():
            out.append((f"{t} ({life.fa(n)})" if n > 1 else t, part.strip()))
    return out


def _clean(x, n):
    return str(x).strip()[:n] if isinstance(x, (str, int, float)) and not isinstance(x, bool) and str(x).strip() else ""


def match_project(projects, ref):
    """ref: شناسه یا (بخشی از) نام. اگر دقیقاً یک پروژه جور شد همان؛ وگرنه None."""
    n = normalize_fa(ref).strip()
    if not n:
        return None
    for p in projects:
        if p["id"].lower() == n or normalize_fa(p["name"]).strip() == n:
            return p
    cands = [p for p in projects if n in normalize_fa(p["name"]) or n in p["id"].lower() or n in normalize_fa(p.get("subtitle") or "")
             or (len(n) >= 3 and normalize_fa(p["name"]) in n)]
    return cands[0] if len(cands) == 1 else None


class Projects:
    def __init__(self, mem):
        self.mem = mem

    # ---------- خواندن ----------
    async def listing(self):
        return await self.mem.list_projects()

    async def detail(self, pid):
        p = await self.mem.get_project(pid)
        if not p:
            return None
        items = await self.mem.project_items(pid)
        return {**p, "tasks": [i for i in items if i["kind"] == "task"], "notes": [i for i in items if i["kind"] == "note"],
                "docs": await self.mem.list_project_docs(pid)}

    # ---------- ثبت از چت ----------
    async def apply_ops(self, ops):
        """ops: [{"op": note|task|done|status, "project", "text", "status"}] → خط‌های تأیید (حقیقت سمت سرور)."""
        notes = []
        projects = await self.mem.list_projects()
        for op in ops:
            p = match_project(projects, op.get("project") or "")
            if not p:
                names = "، ".join(x["name"] for x in projects) or "—"
                notes.append(f"⚠️ پروژهٔ «{op.get('project') or '؟'}» رو پیدا نکردم (پروژه‌ها: {names}).")
                continue
            kind, text = op["op"], op.get("text") or ""
            if kind == "note":
                await self.mem.add_project_item(p["id"], "note", text, source="chat")
                notes.append(f"🗂 «{p['name']}»: یادداشت ثبت شد")
            elif kind == "task":
                await self.mem.add_project_item(p["id"], "task", text, source="chat")
                notes.append(f"🗂 «{p['name']}»: کار تازه اضافه شد: {text}")
            elif kind == "done":
                open_tasks = [i for i in await self.mem.project_items(p["id"], "task") if not i["done"]]
                n = normalize_fa(text)
                hits = [i for i in open_tasks if n and (n in normalize_fa(i["text"]) or normalize_fa(i["text"]) in n)]
                if len(hits) == 1:
                    await self.mem.set_project_item_done(hits[0]["id"], True)
                    notes.append(f"🗂 «{p['name']}»: انجام شد ✓ {hits[0]['text']}")
                elif not hits:
                    await self.mem.add_project_item(p["id"], "note", "انجام شد: " + text, source="chat")
                    notes.append(f"🗂 «{p['name']}»: کاری با این اسم تو فهرست نبود؛ به‌عنوان یادداشت «انجام شد» ثبتش کردم")
                else:
                    notes.append(f"⚠️ «{p['name']}»: چند کار شبیه «{text}» هست؛ دقیق‌تر بگو.")
            elif kind == "status":
                await self.mem.update_project(p["id"], {"status": _clean(op.get("status") or text, STATUS_MAX)})
                notes.append(f"🗂 «{p['name']}»: وضعیت شد «{_clean(op.get('status') or text, STATUS_MAX)}»")
        return notes

    # ---------- برای مغز و تلگرام ----------
    async def prompt(self, max_chars=3200):
        ps = await self.mem.list_projects()
        if not ps:
            return ""
        lines = ["### پروژه‌های کاربر (وضعیت واقعی؛ دربارهٔ آن‌ها حدس نزن، از همین‌ها و از نتایج جست‌وجو بگو. برای ثبت پیشرفت از project_op استفاده کن):"]
        for p in ps:
            line = f"- {p['name']} (id={p['id']}) [{p['status']}]: {p['summary'][:280]}"
            if p.get("open_tasks"):
                line += f" | کارهای باز ({life.fa(p['open_count'])}): " + "؛ ".join(t["text"][:90] for t in p["open_tasks"][:3])
            if p.get("last_note"):
                line += f" | آخرین یادداشت: {p['last_note']['text'][:140]}"
            lines.append(line[:900])
        return "\n".join(lines)[:max_chars]

    async def text(self):
        ps = await self.mem.list_projects()
        if not ps:
            return "هنوز پروژه‌ای ثبت نشده."
        out = ["🗂 پروژه‌های تو:"]
        for p in ps:
            out.append(f"\n{p['icon']} {p['name']} — {p['status']}\n{p['summary'][:220]}")
            if p.get("open_tasks"):
                out.append("   باز: " + "؛ ".join(t["text"] for t in p["open_tasks"][:3]) + (f" (+{life.fa(p['open_count'] - 3)} تای دیگه)" if p["open_count"] > 3 else ""))
            if p.get("last_note"):
                out.append("   آخرین: " + p["last_note"]["text"][:120])
        out.append("\nجزئیات و مستندات کامل: اپ ← هدف‌ها ← پروژه‌ها")
        return "\n".join(out)

    # ---------- ورود از فایل (فقط روی سرور) ----------
    async def import_dir(self, path):
        done = []
        for fn in sorted(os.listdir(path)):
            if not fn.endswith(".json"):
                continue
            meta = json.load(open(os.path.join(path, fn), encoding="utf-8"))
            pid = _clean(meta.get("id"), 40) or os.path.splitext(fn)[0]
            existed = await self.mem.get_project(pid)
            await self.mem.upsert_project({
                "id": pid, "name": _clean(meta.get("name"), 80) or pid, "subtitle": _clean(meta.get("subtitle"), 160),
                "status": _clean(meta.get("status"), STATUS_MAX) or "فعال", "color": _clean(meta.get("color"), 20) or "#E3B35C",
                "icon": _clean(meta.get("icon"), 8) or "🗂", "summary": _clean(meta.get("summary"), 700),
                "meta": {"kpis": [[_clean(a, 60), _clean(b, 80)] for a, b in (meta.get("kpis") or [])][:10]},
                "pos": int(meta.get("pos") or 0)})
            have = {i["text"] for i in await self.mem.project_items(pid)}
            for kind, key in (("task", "tasks"), ("note", "notes")):
                for t in meta.get(key) or []:
                    t = _clean(t, 400)
                    if t and t not in have and not (existed and kind == "task" and have):    # کارهای قبلی کاربر را بهم نریز
                        await self.mem.add_project_item(pid, kind, t, source="import")
            md = meta.get("doc")
            docs = chunk_markdown(open(os.path.join(path, md), encoding="utf-8").read()) if md and os.path.isfile(os.path.join(path, md)) else []
            if docs:
                await self.mem.replace_project_docs(pid, docs)
            done.append((pid, len(docs)))
        return done


def main():
    from .config import Config
    from .memory import Memory
    import asyncio
    if len(sys.argv) < 2:
        sys.exit("استفاده: python -m app.projects <پوشهٔ ورود>")
    cfg = Config.from_env()
    mem = Memory(os.path.join(cfg.data_dir, "mehrdad.db"))
    for pid, n in asyncio.run(Projects(mem).import_dir(sys.argv[1])):
        print(f"پروژه {pid}: {n} بخش مستند")


if __name__ == "__main__":
    main()
