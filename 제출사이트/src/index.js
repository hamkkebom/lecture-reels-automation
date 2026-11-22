// 강의 영상 제출 서버.
// 제출하는 사람: 제출 코드 + 이름 + 강의 제목 + 영상 파일 → 조각(50MB)으로 나눠 R2에 바로 저장.
// 내 PC / 관리자 페이지(/admin): ADMIN_TOKEN으로 목록·상태·내려받기·삭제·제출 코드 변경.
//
// R2 안의 자리
//   raw/<id>/<파일명>   올라온 원본 (3일 뒤 자동 삭제 규칙)
//   rec/<id>           제출 기록 (빈 객체 + customMetadata, 지우기 전까지 남음)
//   acad/<aid>.json    학원 설정 (이름, 전용 제출 코드, 스타일 틀, 색, 드라이브 폴더)
//   acadlogo/<aid>     학원 로고 PNG
//   sys/submit_code    (예전) 학원이 하나도 없을 때만 쓰는 공용 제출 코드
//   sys/pc_seen        내 PC 받아오기 프로그램이 마지막으로 확인한 시각
//   bill/<id>          정산 장부: 제출이 '완료(전달)'가 되고 릴스가 1개 이상일 때 남는다.
//                      처음 완료된 달에 잡히고(다시 전달해도 그 달 그대로), 기록을 지워도 남는다.
//   sys/telegram.json  텔레그램 알림 연결 {token, chat, bot} (관리자 페이지에서 연결, 토큰은 밖으로 돌려주지 않음)

const PART_MAX = 100 * 1024 * 1024; // 조각 하나 최대 (Workers 요청 본문 한도 안)
const MAX_FILE = 40 * 1024 ** 3; // 파일 하나 최대 40GB
const LINK_HOURS = 6; // 관리자 페이지 내려받기 링크 유효 시간
// delivering = 관리자 페이지에서 '드라이브로 전달'을 눌러 내 PC가 올리기를 기다리는 중
const STATUSES = ["submitted", "received", "working", "ready", "delivering", "done", "deleted"];
// 기록(rec/)은 R2 메타데이터 2KB 한도 안에 둔다: 파일명은 key 안에 있으니 따로 두지 않는다.
const slim = meta => { const { filename, ...rest } = meta || {}; return rest; };
const fileOf = key => String(key || "").split("/").slice(2).join("/");
const ID_RE = /^\d{4}-\d\d-\d\d_[0-9a-f]{8}$/;

const json = (data, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });

function same(a, b) {
  // 비밀값 비교 (길이·내용)
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

function safeName(s, max = 60) {
  return String(s || "")
    .normalize("NFC")
    .replace(/[\\/:*?"<>|\x00-\x1f]/g, "_")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, max) || "이름없음";
}

const rawKey = key => typeof key === "string" && key.startsWith("raw/") && !key.includes("..");
const idOf = key => key.split("/")[1];

// ---- 제출 코드 (관리자 페이지에서 바꾸면 R2에 저장, 30초 캐시) ----
let codeCache = { v: "", t: 0 };
async function submitCode(env) {
  if (codeCache.v && Date.now() - codeCache.t < 30_000) return codeCache.v;
  const o = await env.BUCKET.get("sys/submit_code");
  const v = o ? (await o.text()).trim() : env.SUBMIT_CODE || "";
  codeCache = { v, t: Date.now() };
  return v;
}
// ---- 학원 (학원마다 전용 제출 코드) ----
// 스타일 틀 목록. 편집 프로그램(PC)이 같은 id로 틀을 고른다.
// brand.py 의 TEMPLATES 와 id·이름을 맞춘다.
const TEMPLATES = [
  { id: "h4", name: "기본 (남색 카드)" },
  { id: "black", name: "블랙 (진한 글씨)" },
  { id: "chalk", name: "칠판 (초록 바탕)" },
  { id: "brand", name: "학원색 바탕" },
];
const AID_RE = /^[0-9a-f]{6}$/;
const HEX_RE = /^[0-9A-Fa-f]{6}$/;
const DEFAULT_COLORS = { accent: "FFD400", english: "3DDC5A", point: "FF8A1F" };

let acadCache = { list: null, t: 0 };
async function academies(env, fresh = false) {
  if (!fresh && acadCache.list && Date.now() - acadCache.t < 30_000) return acadCache.list;
  const objs = await listAll(env, "acad/");
  const list = (await Promise.all(objs.map(async o => {
    const r = await env.BUCKET.get(o.key);
    try { return r ? JSON.parse(await r.text()) : null; } catch { return null; }
  }))).filter(Boolean).sort((a, b) => String(a.created).localeCompare(String(b.created)));
  acadCache = { list, t: Date.now() };
  return list;
}

// 제출 코드 → 학원. 학원이 하나도 없으면 예전 공용 코드로 받는다 (학원 정보 없음).
async function academyForCode(given, env) {
  if (typeof given !== "string" || !given) return null;
  const list = await academies(env);
  if (list.length) return list.find(a => same(given, a.code)) || null;
  const c = await submitCode(env);
  return c.length >= 4 && same(given, c) ? { id: "", name: "" } : null;
}
const codeOk = async (given, env) => !!(await academyForCode(given, env));
const BAD_CODE = () => json({ error: "제출 코드가 맞지 않습니다." }, 403);

// ---- 제출하는 사람 ----
async function start(req, env) {
  const b = await req.json().catch(() => ({}));
  const acad = await academyForCode(b.code, env);
  if (!acad) return BAD_CODE();
  const size = Number(b.size);
  if (!b.name || !b.title || !b.filename) return json({ error: "이름, 강의 제목, 파일을 모두 넣어 주세요." }, 400);
  if (b.consent !== true) return json({ error: "강사 동의 확인에 체크해 주세요. (체크 칸이 안 보이면 페이지를 새로고침해 주세요)" }, 400);
  if (!(size > 0) || size > MAX_FILE) return json({ error: "파일 크기가 허용 범위를 벗어났습니다." }, 400);
  const day = new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10); // 한국 날짜
  const id = crypto.randomUUID().replace(/-/g, "").slice(0, 8);
  const key = `raw/${day}_${id}/${safeName(b.filename, 120)}`;
  const up = await env.BUCKET.createMultipartUpload(key, {
    customMetadata: {
      name: safeName(b.name, 40),
      title: safeName(b.title, 80),
      filename: safeName(b.filename, 120),
      size: String(size),
      submitted: new Date().toISOString(),
      consent: new Date().toISOString(), // 강사 동의 확인에 체크한 시각
      academy: acad.id,
      academyName: acad.name,
    },
  });
  return json({ key, uploadId: up.uploadId, academyName: acad.name });
}

async function part(req, env, url) {
  if (!(await codeOk(req.headers.get("x-code"), env))) return BAD_CODE();
  const key = url.searchParams.get("key");
  const uploadId = url.searchParams.get("uploadId");
  const n = Number(url.searchParams.get("part"));
  const len = Number(req.headers.get("content-length"));
  if (!rawKey(key) || !uploadId || !(n >= 1 && n <= 10000)) return json({ error: "잘못된 요청" }, 400);
  if (!(len > 0) || len > PART_MAX) return json({ error: "조각 크기가 잘못되었습니다." }, 400);
  const up = env.BUCKET.resumeMultipartUpload(key, uploadId);
  const p = await up.uploadPart(n, req.body);
  return json({ partNumber: p.partNumber, etag: p.etag });
}

async function complete(req, env, ctx) {
  const b = await req.json().catch(() => ({}));
  if (!(await codeOk(b.code, env))) return BAD_CODE();
  if (!rawKey(b.key) || !b.uploadId || !Array.isArray(b.parts)) return json({ error: "잘못된 요청" }, 400);
  const up = env.BUCKET.resumeMultipartUpload(b.key, b.uploadId);
  const obj = await up.complete(b.parts.sort((x, y) => x.partNumber - y.partNumber));
  // 실제 R2의 complete() 결과에는 customMetadata가 비어 있을 수 있어 항상 다시 읽는다
  const meta = (await env.BUCKET.head(b.key))?.customMetadata || {};
  // 실제 올라온 크기 확인 (처음에 알린 크기와 다르거나 너무 크면 버림)
  if (obj.size > MAX_FILE || String(obj.size) !== String(meta.size)) {
    await env.BUCKET.delete(b.key);
    return json({ error: "올라온 파일 크기가 맞지 않습니다. 다시 시도해 주세요." }, 400);
  }
  await env.BUCKET.put("rec/" + idOf(b.key), "", {
    customMetadata: { ...slim(meta), key: b.key, size: String(obj.size), status: "submitted", memo: "", updated: new Date().toISOString() },
  });
  ctx?.waitUntil(notify(env, [
    "새 제출이 들어왔습니다",
    meta.academyName && `학원: ${meta.academyName}`,
    `이름: ${meta.name || ""}`,
    `강의: ${meta.title || ""}`,
    `크기: ${(obj.size / 1024 ** 3).toFixed(2)} GB`,
  ]));
  return json({ ok: true, size: obj.size });
}

async function abort(req, env) {
  const b = await req.json().catch(() => ({}));
  if (!(await codeOk(b.code, env))) return BAD_CODE();
  if (!rawKey(b.key) || !b.uploadId) return json({ error: "잘못된 요청" }, 400);
  await env.BUCKET.resumeMultipartUpload(b.key, b.uploadId).abort().catch(() => {});
  return json({ ok: true });
}

// ---- 관리자 (내 PC, 관리자 페이지) ----
// 내 PC는 ADMIN_TOKEN, 관리자 페이지는 비밀번호로 받은 세션(30일)
const SESSION_DAYS = 30;
const MAX_FAILS = 10;
const LOCK_MS = 10 * 60 * 1000;
async function admin(req, env) {
  const t = (req.headers.get("authorization") || "").replace(/^Bearer /, "");
  if ((env.ADMIN_TOKEN || "").length < 20) return false;
  if (same(t, env.ADMIN_TOKEN)) return true;
  const m = /^s\.(\d+)\.([0-9a-f]{64})$/.exec(t);
  return !!m && Number(m[1]) > Date.now() / 1000 && same(m[2], await hmac(env, `session\n${m[1]}`));
}

async function login(req, env) {
  // 마구 넣어 보기 막기: 10분 안에 10번 틀리면 10분 동안 잠금 (내 PC 받아오기는 영향 없음)
  const now = Date.now();
  const fo = await env.BUCKET.get("sys/login_fail");
  let fail = { n: 0, since: now };
  try { if (fo) fail = JSON.parse(await fo.text()); } catch {}
  if (now - fail.since > LOCK_MS) fail = { n: 0, since: now };
  if (fail.n >= MAX_FAILS) {
    const min = Math.ceil((fail.since + LOCK_MS - now) / 60000);
    return json({ error: `비밀번호를 너무 여러 번 틀려 잠겼습니다. ${min}분 뒤 다시 해 주세요.` }, 429);
  }
  const b = await req.json().catch(() => ({}));
  if (!(env.ADMIN_PASSWORD || "").length || !same(String(b.password || ""), env.ADMIN_PASSWORD)) {
    fail.n += 1;
    if (fail.n >= MAX_FAILS) fail.since = now; // 잠금은 마지막 실패부터 10분
    await env.BUCKET.put("sys/login_fail", JSON.stringify(fail));
    return json({ error: "비밀번호가 맞지 않습니다." }, 401);
  }
  if (fo) await env.BUCKET.delete("sys/login_fail");
  const exp = Math.floor(Date.now() / 1000) + SESSION_DAYS * 86400;
  return json({ token: `s.${exp}.${await hmac(env, `session\n${exp}`)}` });
}

async function listAll(env, prefix) {
  const out = [];
  let cursor;
  do {
    const r = await env.BUCKET.list({ prefix, cursor, include: ["customMetadata"] });
    out.push(...r.objects);
    cursor = r.truncated ? r.cursor : undefined;
  } while (cursor);
  return out;
}

// 내 PC 받아오기 프로그램용: 사이트에 남아 있는 원본 목록
async function list(req, env) {
  if (req.headers.get("x-client") === "pc") await env.BUCKET.put("sys/pc_seen", new Date().toISOString());
  const raws = await listAll(env, "raw/");
  return json({ items: raws.map(o => ({ key: o.key, size: o.size, uploaded: o.uploaded, meta: o.customMetadata || {} })) });
}

// 관리자 페이지용: 제출 기록 전체 + PC 상태 + 제출 코드
async function records(env) {
  const [recs, raws, seen, acads] = await Promise.all([
    listAll(env, "rec/"),
    listAll(env, "raw/"),
    env.BUCKET.get("sys/pc_seen"),
    academies(env, true),
  ]);
  const rawById = new Map(raws.map(o => [idOf(o.key), o]));
  const items = recs.map(o => {
    const id = o.key.slice(4);
    const md = o.customMetadata || {};
    return { id, ...md, filename: md.filename || fileOf(md.key), onSite: rawById.has(id) };
  });
  const known = new Set(items.map(i => i.id));
  for (const [id, o] of rawById) {
    if (!known.has(id)) items.push({ id, ...(o.customMetadata || {}), key: o.key, size: String(o.size), status: "submitted", memo: "", onSite: true });
  }
  items.sort((a, b) => String(b.submitted || "").localeCompare(String(a.submitted || "")));
  return json({ items, pcSeen: seen ? await seen.text() : null, academies: acads, templates: TEMPLATES });
}

// 기록 고치기 (기록이 없으면 원본의 정보로 새로 만든다)
async function patchRec(env, id, patch) {
  const k = "rec/" + id;
  let meta = (await env.BUCKET.head(k))?.customMetadata;
  if (!meta) {
    const r = await env.BUCKET.list({ prefix: `raw/${id}/`, include: ["customMetadata"] });
    const o = r.objects[0];
    if (!o) return false;
    meta = { ...(o.customMetadata || {}), key: o.key, size: String(o.size), status: "submitted", memo: "" };
  }
  await env.BUCKET.put(k, "", { customMetadata: { ...slim(meta), ...patch, updated: new Date().toISOString() } });
  return true;
}

async function setStatus(req, env) {
  const b = await req.json().catch(() => ({}));
  if (!ID_RE.test(b.id || "")) return json({ error: "잘못된 요청" }, 400);
  const patch = {};
  if (b.status !== undefined) {
    if (!STATUSES.includes(b.status)) return json({ error: "없는 상태" }, 400);
    patch.status = b.status;
    patch.changed = new Date().toISOString(); // 이 상태가 된 시각
  }
  if (b.memo !== undefined) patch.memo = String(b.memo).replace(/[\x00-\x1f]/g, " ").slice(0, 100); // R2 메타데이터 2KB 한도 안
  if (b.reels !== undefined) { // 만든 릴스 개수 (정산 기준)
    const n = Number(b.reels);
    if (!Number.isInteger(n) || n < 0 || n > 999) return json({ error: "릴스 개수가 잘못되었습니다." }, 400);
    patch.reels = String(n);
  }
  if (b.delivered === true) patch.delivered = new Date().toISOString(); // 드라이브에 올린 시각 (내 PC가 보냄)
  if (b.academy !== undefined) { // 학원을 잘못 붙였거나 예전 제출에 학원을 붙일 때
    const a = (await academies(env, true)).find(x => x.id === b.academy);
    if (!a) return json({ error: "없는 학원" }, 400);
    patch.academy = a.id;
    patch.academyName = a.name;
  }
  if (!(await patchRec(env, b.id, patch))) return json({ error: "기록이 없습니다." }, 404);
  if (patch.status === "done" || patch.reels !== undefined) await bill(env, b.id);
  if (patch.status === "ready" && String(patch.memo || "").startsWith("전달 실패")) { // 내 PC가 드라이브 전달에 실패
    const rec = (await env.BUCKET.head("rec/" + b.id))?.customMetadata || {};
    await notify(env, ["드라이브 전달에 실패했습니다", `${rec.academyName || ""} / ${rec.name || ""} / ${rec.title || ""}`, patch.memo]);
  }
  return json({ ok: true });
}

// ---- 텔레그램 알림 ----
// 사장님이 BotFather로 만든 봇 토큰을 관리자 페이지에 넣고, 봇에게 말을 한 번 걸면 그 대화방으로 알림이 간다.
const tgApi = (env, token, method) => `${env.TELEGRAM_API || "https://api.telegram.org"}/bot${token}/${method}`;
async function tgCall(env, token, method, body) {
  const r = await fetch(tgApi(env, token, method), {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body || {}),
  });
  const d = await r.json().catch(() => ({}));
  if (!d.ok) throw new Error(d.description || "텔레그램 응답 " + r.status);
  return d.result;
}
async function tgConf(env) {
  const o = await env.BUCKET.get("sys/telegram.json");
  try { return o ? JSON.parse(await o.text()) : null; } catch { return null; }
}
// 알림 실패로 제출·상태 바꾸기가 실패하면 안 된다 → 오류는 삼킨다
async function notify(env, lines) {
  try {
    const c = await tgConf(env);
    if (!c?.token || !c?.chat) return;
    await tgCall(env, c.token, "sendMessage", { chat_id: c.chat, text: lines.filter(Boolean).join("\n"), disable_web_page_preview: true });
  } catch (e) { console.error("telegram", e); }
}
async function tgStatus(env) {
  const c = await tgConf(env);
  return json({ connected: !!(c?.token && c?.chat), bot: c?.bot || "" });
}
async function tgConnect(req, env) {
  const b = await req.json().catch(() => ({}));
  const old = await tgConf(env);
  const token = (String(b.token || "").match(/\d{5,}:[A-Za-z0-9_-]{30,}/) || [String(b.token || "").trim()])[0] || old?.token || "";
  if (!/^\d{5,}:[A-Za-z0-9_-]{30,}$/.test(token)) return json({ error: "봇 토큰 모양이 아닙니다. BotFather가 준 '숫자:글자' 전체를 넣어 주세요." }, 400);
  let me, ups;
  try {
    me = await tgCall(env, token, "getMe");
    ups = await tgCall(env, token, "getUpdates", { limit: 100, timeout: 0 });
  } catch (e) {
    return json({ error: "텔레그램이 이 토큰을 받지 않습니다: " + e.message }, 400);
  }
  const chats = ups.map(u => (u.message || u.edited_message || u.my_chat_member)?.chat).filter(c => c && c.type === "private");
  const chat = chats.length ? chats[chats.length - 1].id : (old?.token === token ? old?.chat : null);
  if (!chat) return json({ error: `텔레그램에서 @${me.username} 봇을 찾아 '시작'을 누르거나 아무 말이나 보낸 뒤 다시 눌러 주세요.` }, 400);
  await env.BUCKET.put("sys/telegram.json", JSON.stringify({ token, chat, bot: me.username }));
  try {
    await tgCall(env, token, "sendMessage", { chat_id: chat, text: "연결되었습니다. 새 제출과 드라이브 전달 실패를 여기로 알려 드립니다." });
  } catch (e) {
    return json({ error: "연결은 저장했지만 시험 메시지를 못 보냈습니다: " + e.message }, 502);
  }
  return json({ ok: true, bot: me.username });
}
async function tgTest(env) {
  const c = await tgConf(env);
  if (!c?.token || !c?.chat) return json({ error: "텔레그램이 연결되어 있지 않습니다." }, 400);
  try {
    await tgCall(env, c.token, "sendMessage", { chat_id: c.chat, text: "시험 알림입니다. 잘 받으셨으면 연결이 정상입니다." });
  } catch (e) {
    return json({ error: "보내지 못했습니다: " + e.message }, 502);
  }
  return json({ ok: true });
}

// ---- 정산 장부 ----
const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;
const kstMonth = iso => new Date(new Date(iso).getTime() + 9 * 3600e3).toISOString().slice(0, 7);

// 제출이 완료(전달) + 릴스 1개 이상이면 장부에 넣거나 고친다 (달은 처음 넣을 때 정함)
async function bill(env, id) {
  const rec = (await env.BUCKET.head("rec/" + id))?.customMetadata;
  const reels = Number(rec?.reels || 0);
  if (!rec || rec.status !== "done" || !(reels > 0)) return;
  const old = (await env.BUCKET.head("bill/" + id))?.customMetadata;
  const at = old?.at || rec.delivered || new Date().toISOString();
  await env.BUCKET.put("bill/" + id, "", {
    customMetadata: {
      month: old?.month || kstMonth(at), at,
      academy: rec.academy || "", academyName: rec.academyName || "",
      name: rec.name || "", title: rec.title || "",
      reels: String(reels), via: rec.delivered ? "drive" : "manual",
      updated: new Date().toISOString(),
    },
  });
}

async function billing(env) {
  const objs = await listAll(env, "bill/");
  const entries = objs.map(o => ({ id: o.key.slice(5), ...(o.customMetadata || {}) }))
    .sort((a, b) => String(a.at).localeCompare(String(b.at)));
  return json({ entries, academies: await academies(env) });
}

// 장부 고치기: 달 옮기기, 릴스 개수 고치기
async function editBill(req, env) {
  const b = await req.json().catch(() => ({}));
  if (!ID_RE.test(b.id || "")) return json({ error: "잘못된 요청" }, 400);
  const md = (await env.BUCKET.head("bill/" + b.id))?.customMetadata;
  if (!md) return json({ error: "장부에 없습니다." }, 404);
  if (b.month !== undefined) {
    if (!MONTH_RE.test(b.month)) return json({ error: "달이 잘못되었습니다 (예: 2026-11)." }, 400);
    md.month = b.month;
  }
  if (b.reels !== undefined) {
    const n = Number(b.reels);
    if (!Number.isInteger(n) || n < 1 || n > 999) return json({ error: "릴스 개수가 잘못되었습니다." }, 400);
    md.reels = String(n);
  }
  await env.BUCKET.put("bill/" + b.id, "", { customMetadata: { ...md, updated: new Date().toISOString() } });
  return json({ ok: true });
}

async function delBill(env, url) {
  const id = url.searchParams.get("id") || "";
  if (!ID_RE.test(id)) return json({ error: "잘못된 요청" }, 400);
  await env.BUCKET.delete("bill/" + id);
  return json({ ok: true });
}

// 원본 지우기. reason=received(내 PC가 받음, 기본) | deleted(관리자가 그냥 지움)
async function del(env, url) {
  const key = url.searchParams.get("key");
  if (!rawKey(key)) return json({ error: "잘못된 요청" }, 400);
  const reason = url.searchParams.get("reason") === "deleted" ? "deleted" : "received";
  const id = idOf(key);
  if (ID_RE.test(id)) {
    const now = new Date().toISOString();
    if (reason === "deleted") await patchRec(env, id, { status: "deleted", deleted: now });
    else {
      // 관리자가 이미 '작업 중'·'완료' 등으로 바꿨으면 상태는 그대로 두고 받은 시각만 남김
      const cur = (await env.BUCKET.head("rec/" + id))?.customMetadata?.status;
      await patchRec(env, id, !cur || cur === "submitted" ? { status: "received", received: now } : { received: now });
    }
  }
  await env.BUCKET.delete(key);
  return json({ ok: true });
}

// 기록까지 완전히 지우기 (원본이 남아 있으면 같이)
async function delRecord(env, url) {
  const id = url.searchParams.get("id") || "";
  if (!ID_RE.test(id)) return json({ error: "잘못된 요청" }, 400);
  const r = await env.BUCKET.list({ prefix: `raw/${id}/` });
  await env.BUCKET.delete(["rec/" + id, ...r.objects.map(o => o.key)]);
  return json({ ok: true });
}

// ---- 학원 관리 ----
async function saveAcademy(req, env) {
  const b = await req.json().catch(() => ({}));
  const list = await academies(env, true);
  const old = b.id ? list.find(a => a.id === b.id) : null;
  if (b.id && !old) return json({ error: "없는 학원" }, 404);
  const name = safeName(b.name, 40);
  const code = String(b.code || "").trim();
  if (!String(b.name || "").trim()) return json({ error: "학원 이름을 넣어 주세요." }, 400);
  if (!/^[A-Za-z0-9]{6,32}$/.test(code)) return json({ error: "제출 코드는 영문·숫자 6~32자로 정해 주세요." }, 400);
  if (list.some(a => a.id !== b.id && a.code.toLowerCase() === code.toLowerCase())) return json({ error: "다른 학원이 이미 쓰는 제출 코드입니다." }, 400);
  if (list.some(a => a.id !== b.id && a.name === name)) return json({ error: "같은 이름의 학원이 이미 있습니다." }, 400);
  const template = TEMPLATES.some(t => t.id === b.template) ? b.template : TEMPLATES[0].id;
  const colors = {};
  for (const k of Object.keys(DEFAULT_COLORS)) {
    const v = String(b.colors?.[k] || DEFAULT_COLORS[k]).replace(/^#/, "");
    if (!HEX_RE.test(v)) return json({ error: "색 값이 잘못되었습니다." }, 400);
    colors[k] = v.toUpperCase();
  }
  const a = {
    id: old ? old.id : crypto.randomUUID().replace(/-/g, "").slice(0, 6),
    name, code, template, colors,
    drive: String(b.drive || "").trim().slice(0, 300),
    hasLogo: old ? !!old.hasLogo : false,
    created: old ? old.created : new Date().toISOString(),
    updated: new Date().toISOString(),
  };
  await env.BUCKET.put(`acad/${a.id}.json`, JSON.stringify(a));
  acadCache = { list: null, t: 0 };
  return json({ ok: true, academy: a });
}

async function delAcademy(env, url) {
  const id = url.searchParams.get("id") || "";
  if (!AID_RE.test(id)) return json({ error: "잘못된 요청" }, 400);
  await env.BUCKET.delete([`acad/${id}.json`, `acadlogo/${id}`]);
  acadCache = { list: null, t: 0 };
  return json({ ok: true });
}

async function putLogo(req, env, url) {
  const id = url.searchParams.get("id") || "";
  const a = AID_RE.test(id) && (await academies(env, true)).find(x => x.id === id);
  if (!a) return json({ error: "없는 학원" }, 404);
  const len = Number(req.headers.get("content-length"));
  if (!(len > 0) || len > 5 * 1024 * 1024) return json({ error: "로고는 5MB 이하 PNG로 올려 주세요." }, 400);
  const buf = await req.arrayBuffer();
  const sig = new Uint8Array(buf.slice(0, 8));
  if (![0x89, 0x50, 0x4e, 0x47].every((x, i) => sig[i] === x)) return json({ error: "PNG 파일만 올릴 수 있습니다 (투명 배경 권장)." }, 400);
  await env.BUCKET.put(`acadlogo/${id}`, buf, { httpMetadata: { contentType: "image/png" } });
  await env.BUCKET.put(`acad/${id}.json`, JSON.stringify({ ...a, hasLogo: true, updated: new Date().toISOString() }));
  acadCache = { list: null, t: 0 };
  return json({ ok: true });
}

async function getLogo(env, url) {
  const id = url.searchParams.get("id") || "";
  const o = AID_RE.test(id) && (await env.BUCKET.get(`acadlogo/${id}`));
  if (!o) return json({ error: "로고 없음" }, 404);
  return new Response(o.body, { headers: { "content-type": "image/png", "cache-control": "no-store" } });
}

// ---- 브라우저 내려받기용 서명 링크 ----
async function hmac(env, msg) {
  const k = await crypto.subtle.importKey("raw", new TextEncoder().encode(env.ADMIN_TOKEN), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const s = await crypto.subtle.sign("HMAC", k, new TextEncoder().encode(msg));
  return [...new Uint8Array(s)].map(x => x.toString(16).padStart(2, "0")).join("");
}
const sign = (env, key, exp) => hmac(env, `dl\n${key}\n${exp}`);

async function makeLink(req, env, url) {
  const b = await req.json().catch(() => ({}));
  if (!rawKey(b.key)) return json({ error: "잘못된 요청" }, 400);
  const exp = Math.floor(Date.now() / 1000) + LINK_HOURS * 3600;
  const q = new URLSearchParams({ key: b.key, exp: String(exp), sig: await sign(env, b.key, exp) });
  return json({ url: `${url.origin}/api/dl?${q}` });
}

async function signedGet(req, env, url) {
  const key = url.searchParams.get("key");
  const exp = Number(url.searchParams.get("exp"));
  const sig = url.searchParams.get("sig") || "";
  if (!rawKey(key) || !(exp > Date.now() / 1000) || (env.ADMIN_TOKEN || "").length < 20) return json({ error: "링크가 만료되었습니다." }, 403);
  if (!same(sig, await sign(env, key, exp))) return json({ error: "잘못된 링크" }, 403);
  return serve(req, env, key, true);
}

// 원본 보내기 (이어받기 Range 지원)
async function serve(req, env, key, attachment) {
  const range = req.headers.get("range");
  const m = range && /^bytes=(\d+)-(\d*)$/.exec(range);
  const opts = {};
  const GONE = () => json({ error: "없음 (이미 받았거나 지워졌습니다)" }, 404);
  if (m) {
    const head = await env.BUCKET.head(key);
    if (!head) return GONE();
    const s = Number(m[1]);
    const e = m[2] ? Math.min(Number(m[2]), head.size - 1) : head.size - 1;
    if (s >= head.size || e < s) return new Response(null, { status: 416, headers: { "content-range": `bytes */${head.size}` } });
    opts.range = { offset: s, length: e - s + 1 };
  }
  const obj = await env.BUCKET.get(key, opts);
  if (!obj) return GONE();
  const headers = new Headers({ "content-type": "application/octet-stream", "accept-ranges": "bytes", "cache-control": "no-store" });
  if (attachment) {
    const md = obj.customMetadata || {};
    const ext = (key.match(/\.[A-Za-z0-9]{1,6}$/) || [".mp4"])[0];
    const name = `${idOf(key).slice(0, 10)}_${md.name || ""}_${md.title || ""}${ext}`;
    headers.set("content-disposition", `attachment; filename="video${ext}"; filename*=UTF-8''${encodeURIComponent(name)}`);
  }
  if (m) {
    const s = opts.range.offset;
    const e = opts.range.length ? s + opts.range.length - 1 : obj.size - 1;
    headers.set("content-range", `bytes ${s}-${e}/${obj.size}`);
    headers.set("content-length", String(e - s + 1));
    return new Response(obj.body, { status: 206, headers });
  }
  headers.set("content-length", String(obj.size));
  return new Response(obj.body, { headers });
}

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    const p = url.pathname;
    const M = req.method;
    try {
      if (p === "/api/start" && M === "POST") return await start(req, env);
      if (p === "/api/part" && M === "PUT") return await part(req, env, url);
      if (p === "/api/complete" && M === "POST") return await complete(req, env, ctx);
      if (p === "/api/abort" && M === "POST") return await abort(req, env);
      if (p === "/api/dl" && M === "GET") return await signedGet(req, env, url);
      if (p === "/api/login" && M === "POST") return await login(req, env);
      if (p.startsWith("/api/admin/")) {
        if (!(await admin(req, env))) return json({ error: "권한 없음" }, 401);
        if (p === "/api/admin/list" && M === "GET") return await list(req, env);
        if (p === "/api/admin/records" && M === "GET") return await records(env);
        if (p === "/api/admin/get" && M === "GET") {
          const key = url.searchParams.get("key");
          return rawKey(key) ? await serve(req, env, key, false) : json({ error: "잘못된 요청" }, 400);
        }
        if (p === "/api/admin/link" && M === "POST") return await makeLink(req, env, url);
        if (p === "/api/admin/status" && M === "POST") return await setStatus(req, env);
        if (p === "/api/admin/academies" && M === "GET") return json({ academies: await academies(env, true), templates: TEMPLATES });
        if (p === "/api/admin/academy" && M === "POST") return await saveAcademy(req, env);
        if (p === "/api/admin/academy" && M === "DELETE") return await delAcademy(env, url);
        if (p === "/api/admin/academy/logo" && M === "PUT") return await putLogo(req, env, url);
        if (p === "/api/admin/academy/logo" && M === "GET") return await getLogo(env, url);
        if (p === "/api/admin/delete" && M === "DELETE") return await del(env, url);
        if (p === "/api/admin/record" && M === "DELETE") return await delRecord(env, url);
        if (p === "/api/admin/billing" && M === "GET") return await billing(env);
        if (p === "/api/admin/billing" && M === "POST") return await editBill(req, env);
        if (p === "/api/admin/billing" && M === "DELETE") return await delBill(env, url);
        if (p === "/api/admin/telegram" && M === "GET") return await tgStatus(env);
        if (p === "/api/admin/telegram" && M === "POST") return await tgConnect(req, env);
        if (p === "/api/admin/telegram" && M === "DELETE") { await env.BUCKET.delete("sys/telegram.json"); return json({ ok: true }); }
        if (p === "/api/admin/telegram/test" && M === "POST") return await tgTest(env);
      }
      if (p.startsWith("/api/")) return json({ error: "없는 주소" }, 404);
      return env.ASSETS.fetch(req);
    } catch (e) {
      console.error(e);
      return json({ error: "서버 오류가 났습니다. 잠시 뒤 다시 시도해 주세요." }, 500);
    }
  },
};
