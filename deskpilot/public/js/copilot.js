/**
 * Deskpilot — in-Desk guided assistant.
 *
 * Injected on every Desk page via app_include_js. The displayed name, greeting and
 * avatar come from Deskpilot Settings via api.status(); nothing here is hardcoded
 * branding.
 *
 * INPUT : text + Live voice mode (continuous mic) + file attach (real upload)
 * OUTPUT: chat text + voice (TTS, only in Live mode) + UI control (navigate/spotlight/fill)
 *
 * Voice UX (v3): one sound-wave button toggles LIVE mode — a hands-free loop:
 *   listen -> transcribe -> ask brain -> answer (spoken) -> listen again.
 * No separate mic/speaker buttons. TTS is silent outside Live mode.
 */
(function () {
	if (window.__deskpilotLoaded) return;
	window.__deskpilotLoaded = true;

	const LS_KEY = "deskpilot_state";
	const state = Object.assign(
		{ open: false, dismissed: false },
		JSON.parse(localStorage.getItem(LS_KEY) || "{}")
	);
	const save = () => localStorage.setItem(LS_KEY, JSON.stringify(state));

	let brain = null;            // {provider, model, helper_name, greeting, avatar_url}
	let helperName = "Deskpilot"; // overwritten by applyBrand() from api.status()
	let greeting = "";            // ditto; "" = use the built-in default
	let warmed = false;          // LLM warmed up (avoids ~65-80s cold-start timeout)
	let live = false;            // Live voice mode on/off
	let phase = "idle";          // idle | listening | thinking | speaking
	let recog = null;
	// Append-only list. Was a single `pendingAttachment`, so a second upload
	// silently destroyed the first.
	let attachments = [];        // [{name, type, url}]

	// Per-TAB session. Deliberately sessionStorage, not localStorage: with
	// localStorage two Desk tabs share one session id and the server-side
	// in-flight lock makes the second tab answer "still working on your last one".
	const SID_KEY = "deskpilot_sid";
	const getSid = () => sessionStorage.getItem(SID_KEY) || null;
	const setSid = (s) => { if (s) sessionStorage.setItem(SID_KEY, s); };

	const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;  // matches System Settings max_file_size
	// Sized from the server's own budget (status.max_job_seconds) plus headroom, so
	// the SERVER times out first and can return a partial answer instead of the
	// browser abandoning a job that keeps running.
	let replyTimeoutMs = 170000;
	let currentJob = null;                      // job id of the in-flight turn

	/* ----------------------------------------------------------- styles
	   Frappe light theme: white surfaces, blue #2490ef accent, no gold. */
	const css = `
	/* Glass fab: transparent fill + 50% gray ring. The backdrop blur + faint tint
	   are load-bearing, not decoration — FACE is a DARK mark, and the old
	   solid #fff was the only thing keeping it legible. Strip the fill with no
	   compensation and the mascot disappears on Frappe's dark theme. */
	#dp-fab{position:fixed;right:22px;bottom:22px;width:56px;height:56px;border-radius:50%;
		background:rgba(255,255,255,.10);-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);
		box-shadow:0 4px 14px rgba(31,39,46,.14),0 0 0 1px rgba(128,128,128,.5);
		cursor:pointer;z-index:1040;display:flex;align-items:center;justify-content:center;
		transition:transform .18s ease,box-shadow .18s ease,background .18s ease;padding:0;overflow:visible}
	#dp-fab:hover{transform:scale(1.06) translateY(-1px);background:rgba(255,255,255,.18);
		box-shadow:0 8px 22px rgba(31,39,46,.2),0 0 0 1px rgba(36,144,239,.65)}
	/* Dark theme: lift the ink off the dark chrome with a light scrim instead. */
	[data-theme="dark"] #dp-fab,[data-theme-mode="dark"] #dp-fab{background:rgba(230,235,240,.22)}
	[data-theme="dark"] #dp-fab .dp-face,[data-theme-mode="dark"] #dp-fab .dp-face{
		filter:invert(1) hue-rotate(180deg) brightness(1.15)}
	#dp-fab .dp-face{width:88%;height:88%;border-radius:50%;display:block;animation:dp-bob 3.4s ease-in-out infinite;will-change:transform}
	#dp-fab .dp-ring{position:absolute;inset:0;border-radius:50%;border:2px solid #2490ef;opacity:0;pointer-events:none}
	/* DISMISSED = dormant, NOT gone. The fab stays put as a grey translucent
	   outline and fills back to full colour on hover, so a user who dismissed it
	   can always bring it back by clicking. (It used to display:none, which left
	   the console one-liner deskpilot_show() as the only way back — useless for
	   non-technical users.) */
	#dp-fab.dismissed{background:transparent;-webkit-backdrop-filter:none;backdrop-filter:none;
		box-shadow:0 0 0 1px rgba(128,128,128,.38);opacity:.5}
	#dp-fab.dismissed .dp-face{filter:grayscale(1) contrast(.35) brightness(1.25);animation:none}
	#dp-fab.dismissed .dp-ring{display:none}
	#dp-fab.dismissed:hover{opacity:1;background:rgba(255,255,255,.10);
		-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);
		box-shadow:0 4px 14px rgba(31,39,46,.14),0 0 0 1px rgba(128,128,128,.5)}
	#dp-fab.dismissed:hover .dp-face{filter:none;animation:dp-bob 3.4s ease-in-out infinite}
	[data-theme="dark"] #dp-fab.dismissed .dp-face,[data-theme-mode="dark"] #dp-fab.dismissed .dp-face{
		filter:invert(1) hue-rotate(180deg) grayscale(1) brightness(.85)}
	[data-theme="dark"] #dp-fab.dismissed:hover .dp-face,[data-theme-mode="dark"] #dp-fab.dismissed:hover .dp-face{
		filter:invert(1) hue-rotate(180deg) brightness(1.15)}
	/* character states */
	#dp-fab.listening{box-shadow:0 4px 14px rgba(31,39,46,.22),0 0 0 2px #2490ef,0 0 22px rgba(36,144,239,.45)}
	#dp-fab.listening .dp-face{animation:dp-tilt 1.6s ease-in-out infinite}
	#dp-fab.thinking::after{content:"";position:absolute;inset:-5px;border-radius:50%;border:2px dashed #2490ef;border-top-color:transparent;animation:dp-spin 1.1s linear infinite}
	#dp-fab.talking .dp-face{animation:dp-nod .5s ease-in-out infinite}
	#dp-fab.talking .dp-ring{animation:dp-rings 1.25s ease-out infinite}
	#dp-fab.talking .dp-ring.r2{animation-delay:.62s}
	@keyframes dp-bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}
	@keyframes dp-nod{0%,100%{transform:translateY(0) scale(1)}50%{transform:translateY(-1px) scale(1.05)}}
	@keyframes dp-tilt{0%,100%{transform:rotate(-4deg)}50%{transform:rotate(4deg)}}
	@keyframes dp-spin{to{transform:rotate(360deg)}}
	@keyframes dp-rings{0%{transform:scale(1);opacity:.7}100%{transform:scale(1.9);opacity:0}}
	/* proactive tip bubble */
	#dp-tip{position:fixed;right:92px;bottom:30px;max-width:232px;background:#fff;color:#1f272e;
		padding:11px 26px 11px 13px;border-radius:8px;border:1px solid #d1d8dd;box-shadow:0 8px 22px rgba(31,39,46,.16);
		font-size:12.5px;line-height:1.45;z-index:1042;cursor:pointer;display:none;animation:dp-pop .25s ease}
	#dp-tip:after{content:"";position:absolute;right:-7px;bottom:16px;border:7px solid transparent;border-left-color:#fff}
	#dp-tip b{color:#2490ef}
	#dp-tip .x{position:absolute;top:5px;right:9px;color:#8d99a6;font-size:14px;line-height:1}
	@keyframes dp-pop{from{opacity:0;transform:translateY(6px) scale(.96)}to{opacity:1;transform:none}}
	#dp-panel{position:fixed;right:22px;bottom:94px;width:360px;max-width:92vw;height:520px;max-height:78vh;
		background:#fff;border-radius:10px;box-shadow:0 16px 44px rgba(31,39,46,.24);
		z-index:1041;display:none;flex-direction:column;overflow:hidden;border:1px solid #d1d8dd}
	#dp-panel.open{display:flex}
	/* streaming, not yet verified — visibly a draft, not the answer */
	.dp-b.provisional{opacity:.62;font-style:italic;
		border-left:2px solid #d1d8dd;padding-left:9px;background:transparent}
	.dp-b.provisional::after{content:" \\2026 drafting";font-size:10px;
		font-style:normal;opacity:.75;letter-spacing:.02em}
	[data-theme="dark"] .dp-b.provisional,[data-theme-mode="dark"] .dp-b.provisional{
		border-left-color:#4a5568}
	.dp-head{padding:11px 14px;background:#fff;color:#1f272e;
		display:flex;align-items:center;gap:9px;font-weight:600;letter-spacing:.2px;
		border-bottom:1px solid #e2e6ea}
	.dp-head .sp{flex:1;display:flex;flex-direction:column;line-height:1.15}
	.dp-head .sp b{font-family:inherit;font-weight:600;font-size:14px;letter-spacing:.3px;color:#1f272e}
	.dp-head .sp small{font-weight:400;font-size:10.5px;color:#8d99a6;letter-spacing:.2px}
	.dp-head button{background:transparent;border:0;color:#8d99a6;cursor:pointer;font-size:15px;opacity:.85;padding:2px 6px;border-radius:6px}
	.dp-head button:hover{opacity:1;color:#2490ef;background:#f0f6fc}
	.dp-msgs{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px;background:#f5f7fa}
	.dp-b{max-width:84%;padding:9px 12px;border-radius:8px;font-size:13px;line-height:1.45;white-space:pre-wrap;word-wrap:break-word}
	.dp-b.user{align-self:flex-end;background:#2490ef;color:#fff;border-bottom-right-radius:2px}
	.dp-b.bot{align-self:flex-start;background:#fff;color:#1f272e;border:1px solid #d1d8dd;border-bottom-left-radius:2px}
	.dp-b.sys{align-self:center;background:transparent;color:#8d99a6;font-size:11px;text-align:center}
	.dp-b.typing{color:#8d99a6;font-style:italic}
	/* rendered markdown — the model replies in markdown and the KB itself now
	   carries markdown from the Drive export, so raw asterisks were showing. */
	.dp-md{white-space:normal}
	.dp-md p{margin:0 0 6px}
	.dp-md p:last-child{margin-bottom:0}
	.dp-md strong{font-weight:600}
	.dp-md ul,.dp-md ol{margin:4px 0 6px;padding-left:18px}
	.dp-md li{margin:1px 0}
	.dp-md code{background:#eef1f4;border-radius:3px;padding:0 3px;font-size:11.5px;
		font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
	.dp-md pre{background:#eef1f4;border-radius:5px;padding:6px 8px;margin:4px 0;
		overflow-x:auto;font-size:11.5px;white-space:pre-wrap;word-break:break-word}
	.dp-md .mdh{font-weight:600;margin:6px 0 2px;color:#1f272e}
	.dp-md .mdq{border-left:2px solid #d1d8dd;padding-left:7px;color:#5c6b78;margin:4px 0}
	.dp-md .mdrow{display:block;padding:1px 0;color:#3b4752}
	.dp-disc{margin-top:7px;padding-top:6px;border-top:1px solid #eef1f4;
		font-size:10.5px;line-height:1.4;color:#8d99a6;font-style:italic}
	.dp-fb{margin-top:5px;display:flex;align-items:center;gap:6px;font-size:11px;color:#8d99a6;flex-wrap:wrap}
	.dp-fb .rep{background:transparent;border:0;padding:0;font-size:11px;color:#2490ef;
		cursor:pointer;text-decoration:underline;font-style:normal}
	.dp-fb .rep:hover{color:#1b7fd6}
	.dp-fb .sep{opacity:.5}
	.dp-fb button{background:transparent;border:0;cursor:pointer;font-size:14px;padding:0 2px;opacity:.75}
	.dp-fb button:hover{opacity:1}
	.dp-foot{padding:10px;border-top:1px solid #e2e6ea;display:flex;align-items:center;gap:6px;background:#fff}
	.dp-foot input[type=text]{flex:1;border:1px solid #d1d8dd;border-radius:6px;padding:8px 12px;font-size:13px;outline:none;min-width:0;background:#fff;color:#1f272e}
	.dp-foot input[type=text]::placeholder{color:#8d99a6}
	.dp-foot input[type=text]:focus{border-color:#2490ef;box-shadow:0 0 0 2px rgba(36,144,239,.18)}
	.dp-ic{width:34px;height:34px;border-radius:6px;border:1px solid #d1d8dd;cursor:pointer;background:#fff;color:#4c5a67;font-size:15px;
		display:flex;align-items:center;justify-content:center;flex:0 0 auto;transition:background .15s,color .15s}
	.dp-ic:hover{background:#f0f6fc;border-color:#a9cdf5}
	.dp-ic.send{background:#2490ef;border-color:#2490ef;color:#fff}
	.dp-ic.send.stop{background:#e0454c;border-color:#e0454c}
	.dp-ic.send.stop:hover{background:#c93a41;border-color:#c93a41}
	.dp-ic.send:hover{background:#1b7fd6;border-color:#1b7fd6}
	.dp-ic[disabled]{opacity:.5;cursor:default}
	/* live sound-wave button */
	.dp-wave{display:flex;align-items:center;justify-content:center;gap:2px;height:18px}
	.dp-wave span{width:3px;height:5px;background:#4c5a67;border-radius:2px}
	.dp-ic.live-on{background:#2490ef;border-color:#2490ef}
	.dp-ic.live-on .dp-wave span{background:#fff}
	.dp-ic.listening{background:#e0454c;border-color:#e0454c}
	.dp-ic.listening .dp-wave span{background:#fff;animation:dp-wave .85s infinite ease-in-out}
	.dp-ic.speaking{background:#2490ef;border-color:#2490ef}
	.dp-ic.speaking .dp-wave span{background:#fff;animation:dp-wave .5s infinite ease-in-out}
	.dp-wave span:nth-child(2){animation-delay:.12s}
	.dp-wave span:nth-child(3){animation-delay:.24s}
	.dp-wave span:nth-child(4){animation-delay:.36s}
	.dp-wave span:nth-child(5){animation-delay:.48s}
	@keyframes dp-wave{0%,100%{height:4px}50%{height:16px}}
	/* spotlight — above Frappe dialogs (which also sit at 1050) */
	#dp-spot{position:fixed;inset:0;z-index:1090;display:none;pointer-events:none}
	/* Dismissable backdrop in FOUR panels around the hole, not one full-screen
	   sheet. Two constraints have to hold at once:
	     1. clicking outside must dismiss (the old overlay was pointer-events:none
	        everywhere, so the click-outside branch was dead code and the button
	        was the only way out);
	     2. the highlighted field itself must stay clickable — "highlight the
	        Customer field" is usually followed by the user filling it in, and a
	        single full-screen backdrop swallows that click.
	   Leaving the hole uncovered satisfies both. */
	#dp-spot .backdrop{position:absolute;pointer-events:auto;background:transparent}
	#dp-spot .hole{position:absolute;border-radius:6px;box-shadow:0 0 0 9999px rgba(31,39,46,.45);
		border:2px solid #2490ef;transition:left .2s ease,top .2s ease,width .2s ease,height .2s ease;
		pointer-events:none}
	#dp-spot .tip{position:absolute;max-width:260px;background:#fff;color:#1f272e;padding:10px 12px;
		border-radius:8px;font-size:12px;line-height:1.4;pointer-events:auto;box-shadow:0 8px 24px rgba(31,39,46,.2);border:1px solid #d1d8dd}
	#dp-spot .tip b{display:block;margin-bottom:3px;color:#2490ef;font-family:inherit}
	#dp-spot .tip button{margin-top:8px;background:#2490ef;color:#fff;border:0;border-radius:6px;padding:4px 12px;cursor:pointer;font-size:12px;font-weight:600}
	#dp-spot .tip .esc{display:block;margin-top:6px;font-size:10.5px;color:#8d99a6}
	/* session history list */
	.dp-hist{position:absolute;inset:44px 0 0 0;background:#fff;overflow-y:auto;
		display:none;flex-direction:column;z-index:3}
	.dp-hist.open{display:flex}
	.dp-hist .hrow{padding:9px 14px;border-bottom:1px solid #f0f2f4;cursor:pointer}
	.dp-hist .hrow:hover{background:#f0f6fc}
	.dp-hist .hrow.cur{background:#f0f6fc}
	.dp-hist .ht{font-size:12.5px;color:#1f272e;font-weight:600;overflow:hidden;
		text-overflow:ellipsis;white-space:nowrap}
	.dp-hist .hp{font-size:11px;color:#8d99a6;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
	.dp-hist .hm{font-size:10px;color:#a6b1bb;margin-top:2px}
	.dp-hist .newc{padding:10px 14px;border-bottom:1px solid #e2e6ea;color:#2490ef;
		font-size:12.5px;font-weight:600;cursor:pointer}
	.dp-hist .newc:hover{background:#f0f6fc}
	.dp-hist .empty{padding:16px 14px;color:#8d99a6;font-size:12px}
	/* attachment chips */
	.dp-atts{display:flex;flex-wrap:wrap;gap:5px;padding:0 10px 8px;background:#fff}
	.dp-atts:empty{display:none}
	.dp-chip{display:inline-flex;align-items:center;gap:5px;max-width:100%;
		background:#f0f6fc;border:1px solid #a9cdf5;border-radius:12px;padding:2px 8px;
		font-size:11px;color:#1f272e;line-height:1.6}
	.dp-chip.err{background:#fdeaea;border-color:#f0b4b4;color:#8b2b2b}
	.dp-chip .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:150px}
	.dp-chip .rm{cursor:pointer;color:#8d99a6;font-weight:700}
	.dp-chip .rm:hover{color:#e0454c}
	`;
	const style = document.createElement("style");
	style.textContent = css;
	document.head.appendChild(style);

	// Mascot, animated Clippy-style. Must be a DARK mark: see the CSS note above —
	// the light theme puts a pale scrim behind it and the dark theme inverts it.
	// Overridable per-site from Deskpilot Settings (applied in applyBrand()).
	const DEFAULT_FACE = "/assets/deskpilot/img/deskpilot_mark.svg";
	let FACE = DEFAULT_FACE;
	const FACE_FAB = `<img class="dp-face" src="${FACE}" alt="Deskpilot" draggable="false">`
		+ `<span class="dp-ring r1"></span><span class="dp-ring r2"></span>`;
		const WAVE = '<span class="dp-wave"><span></span><span></span><span></span><span></span><span></span></span>';

	/* --------------------------------------------------------- elements */
	const fab = el("div", { id: "dp-fab", title: "Deskpilot", html: FACE_FAB });
	const panel = el("div", { id: "dp-panel" });
	panel.innerHTML = `
		<div class="dp-head">
			<span class="sp"><b id="dp-name">Deskpilot</b><small id="dp-sub">connecting…</small></span>
			<button data-act="hist" title="Previous conversations">🕘</button>
			<button data-act="dismiss" title="Close — the icon stays as a faded outline you can click to bring it back">✕</button>
		</div>
		<div class="dp-msgs" id="dp-msgs"></div>
		<div class="dp-hist" id="dp-hist"></div>
		<div class="dp-atts" id="dp-atts"></div>
		<div class="dp-foot">
			<button class="dp-ic" data-act="attach" title="Attach file">📎</button>
			<input type="text" id="dp-in" placeholder="Ask me, or tap the wave to talk…" autocomplete="off">
			<button class="dp-ic live" data-act="live" title="Live voice mode (mic + speaker)">${WAVE}</button>
			<button class="dp-ic send" data-act="send" title="Send">➤</button>
		</div>
		<input type="file" id="dp-file" style="display:none">`;
	const spot = el("div", {
		id: "dp-spot",
		html: '<div class="backdrop bd-t"></div><div class="backdrop bd-r"></div>'
			+ '<div class="backdrop bd-b"></div><div class="backdrop bd-l"></div>'
			+ '<div class="hole"></div><div class="tip"></div>',
	});

	function mount() {
		document.body.appendChild(fab);
		document.body.appendChild(panel);
		document.body.appendChild(spot);
		bind();
		if (state.dismissed) {
			fab.classList.add("dismissed");
			fab.title = helperName + " — click to bring it back";
		}
		if (state.open) openPanel();
		probeBrain();   // greets via applyBrand() once the configured name is known
		// proactive tip on first idle, and again whenever the route changes
		setTimeout(contextTip, 4500);
		try {
			if (frappe.router && frappe.router.on) frappe.router.on("change", () => {
				hideTip();
				// A spotlight is anchored to a node on the OLD page. Leaving it up
				// strands a hole over the new page with nothing to dismiss it.
				clearSpot();
				setTimeout(contextTip, 1400);
			});
		} catch (e) {}
		// keep the model hot while the Desk is open (cold start is ~65-80s).
		// Server-side this is redis-debounced to one real ping per 120s site-wide,
		// and a cron now covers it too, so this is only a nicety for active tabs.
		warmTimer = setInterval(() => { if (brain && brain.provider !== "none" && frappe.call) frappe.call({ method: "deskpilot.api.keep_warm" }); }, 180000);
		subscribeReplies();
		// Keep the hole glued to its field while the page moves under it.
		window.addEventListener("scroll", repositionSpot, true);
		window.addEventListener("resize", repositionSpot);
		document.addEventListener("keydown", (e) => {
			if (e.key !== "Escape") return;
			if (spot.style.display === "block") { clearSpot(); return; }
			if (inFlight) { stopGenerating(); return; }
			const h = hist();
			if (h && h.classList.contains("open")) { h.classList.remove("open"); return; }
			if (state.open) closePanel();
		});
	}

	/* --------------------------------------------- async reply plumbing */
	// job_id -> {resolve, timer, poll}
	const pending = {};
	// frappe.realtime is NOT ready when the widget mounts. The first version of
	// this bailed out silently in that case and never retried, so no handler was
	// ever registered and every reply arrived via the 2.5s polling fallback —
	// which also made streaming look broken. Retry until the socket object exists.
	let subscribed = false;
	let warmTimer = null;
	let disabled = false;      // access-gated off for this user
	function subscribeReplies(attempt) {
		attempt = attempt || 0;
		try {
			if (subscribed) return;
			if (!frappe.realtime || !frappe.realtime.on || !frappe.realtime.socket) {
				if (attempt < 60) setTimeout(() => subscribeReplies(attempt + 1), 500);
				return;
			}
			subscribed = true;
			setSub();
			frappe.realtime.on("deskpilot:reply", (payload) => settle(payload));
			// Live output while the model works. The final `reply` is still the
			// authoritative text — these only make the wait legible.
			frappe.realtime.on("deskpilot:chunk", (p) => {
				const t = turnFor(p); if (!t) return;
				streamInto(t, p.delta || "");
			});
			frappe.realtime.on("deskpilot:progress", (p) => {
				const t = turnFor(p); if (!t) return;
				if (p.reset) {
					// Was: remove the bubble. That left the panel EMPTY for the whole
					// corrective round — measured ~15s on a ui_action guard — which
					// users read as the answer vanishing. Keep it, dimmed, and let the
					// final text replace it.
					t.streamed = "";
					if (t.bubble) {
						// Keep it on screen, dimmed, but stop writing into it: the next
						// round streams into a FRESH bubble. Hold the reference so the
						// dimmed one is either reused or removed at settle time —
						// nulling it outright left a dimmed duplicate above the answer.
						t.bubble.classList.add("provisional");
						t.retracted = t.bubble;
						t.bubble = null;
					}
				}
				if (t.typing) t.typing.textContent = p.text || "working…";
			});
		} catch (e) {}
	}
	// Match an inbound event to its turn. Falls back to the sole in-flight turn:
	// the worker can start emitting before the ask() HTTP callback has registered
	// the job id, and dropping those first chunks would lose the opening words.
	// Strict match only. Realtime events are delivered to the USER's room, so a
	// second tab receives this tab's chunks too; anything looser cross-wires them.
	function turnFor(p) {
		return (p && p.job_id && pending[p.job_id]) || null;
	}
	// Grow a bot bubble as deltas arrive, replacing the "thinking…" placeholder.
	function streamInto(t, delta) {
		if (!delta) return;
		t.streamed = (t.streamed || "") + delta;
		if (!t.bubble) {
			if (t.typing) { t.typing.remove(); t.typing = null; }
			// Marked provisional FROM THE START. What streams is the model's first,
			// unverified attempt: the guards may discard it and re-run the turn (a
			// figure quoted with no tool call, an on-screen action claimed but not
			// performed). Styling it only once that happens is too late — the user has
			// already read it as the answer, then watched it freeze and change.
			t.bubble = bubble("bot provisional", "");
		}
		t.bubble.textContent = t.streamed;
		msgs().scrollTop = msgs().scrollHeight;
	}
	function settle(payload) {
		if (!payload) return;
		const j = payload.job_id;
		const p = j && pending[j];
		if (!p) return;
		clearTimeout(p.timer); clearInterval(p.poll);
		delete pending[j];
		p.resolve({ r: payload, ui: p });
	}
	function awaitReply(job_id, typing) {
		return new Promise((resolve) => {
			const p = { resolve: resolve, typing: typing, streamed: "", bubble: null };
			pending[job_id] = p;
			// Polling fallback: the socket may be down, blocked, or the worker may
			// have published before we subscribed.
			p.poll = setInterval(() => {
				frappe.call({
					method: "deskpilot.api.get_reply", args: { job_id: job_id },
					callback: (r) => { if (r.message && !r.message.pending) settle(r.message); },
					error: () => {},
				});
			}, 2500);
			p.timer = setTimeout(() => {
				clearInterval(p.poll); delete pending[job_id];
				// Don't just walk away: tell the worker to stop too, or it keeps
				// occupying the queue and the GPU for a reply nobody will read.
				try {
					if (frappe.call) frappe.call({ method: "deskpilot.api.cancel",
						args: { job_id: job_id } });
				} catch (e) {}
				resolve({ r: { error: "That took too long, so I stopped waiting." }, ui: p });
			}, replyTimeoutMs);
		});
	}

	function probeBrain() {
		if (typeof frappe === "undefined" || !frappe.call) return;
		frappe.call({
			method: "deskpilot.api.status",
			callback: (r) => {
				brain = r.message || {};
				// Server-side gating (site_config deskpilot_required_role) reports
				// enabled:false rather than throwing, so the widget can remove itself
				// without a console error for users who simply do not have access.
				if (brain.enabled === false) {
					// Offer setup anyway: a System Manager who has gated the widget
					// behind a role they lack would otherwise have no way back in.
					if (brain.can_setup && window.deskpilot && window.deskpilot.setup) {
						window.deskpilot.setup.maybeAutoOpen(brain);
					}
					return teardown();
				}
				if (brain.max_job_seconds) replyTimeoutMs = (brain.max_job_seconds + 20) * 1000;
				applyBrand(brain);
				// The wizard lives in its own bundle; it may not be loaded.
				if (window.deskpilot && window.deskpilot.setup) {
					window.deskpilot.setup.maybeAutoOpen(brain);
				}
				setSub(); warmUp();
			},
			error: () => { brain = { provider: "none" }; applyBrand(null); setSub(); },
		});
	}
	// Name, greeting and avatar are per-site config, not constants. Everything that
	// shows the assistant's identity is repointed here, after status() answers —
	// including the first greeting, which would otherwise fire with the default name
	// and then be contradicted by the header a moment later.
	function applyBrand(b) {
		helperName = (b && b.helper_name) || "Deskpilot";
		greeting = (b && b.greeting) || "";
		FACE = (b && b.avatar_url) || DEFAULT_FACE;
		const img = fab.querySelector(".dp-face");
		if (img) { img.src = FACE; img.alt = helperName; }
		const nameEl = document.getElementById("dp-name");
		if (nameEl) nameEl.textContent = helperName;
		fab.title = state.dismissed ? helperName + " — click to bring it back" : helperName;
		greetOnce();
	}
	function greetOnce() {
		if (disabled || sessionStorage.getItem("dp_greeted")) return;
		sessionStorage.setItem("dp_greeted", "1");
		setTimeout(() => {
			if (disabled) return;
			botSay(greeting || ("Hi 👋 I'm " + helperName + ". Type a request, attach a file, "
				+ "or tap the wave to talk hands-free. Type \"help\" for examples."));
		}, 800);
	}

	// Remove every trace of the widget: this user is not entitled to it.
	function teardown() {
		disabled = true;
		try { clearInterval(warmTimer); } catch (e) {}
		try { if (live) exitLive(); } catch (e) {}
		[fab, panel, spot, tipEl].forEach((n) => { if (n && n.parentNode) n.remove(); });
	}
	function warmUp() {
		if (!brain || brain.provider === "none" || !frappe.call) return;
		setSub("🟡 waking the model…");
		frappe.call({
			method: "deskpilot.api.keep_warm",
			callback: (r) => { warmed = !!(r.message && r.message.warm); setSub(); },
			error: () => { setSub(); },
		});
	}
	function setSub(override) {
		const sub = document.getElementById("dp-sub"); if (!sub) return;
		if (override) { sub.textContent = override; return; }
		// "· live" means the realtime socket is subscribed, so answers stream in.
		// Without it we are on the slower polling fallback — worth surfacing,
		// because a broken socket is invisible otherwise.
		if (brain && brain.provider && brain.provider !== "none")
			sub.textContent = "🟢 " + (brain.model || brain.provider) + (subscribed ? " · live" : " · polling");
		else sub.textContent = "🔴 model unavailable";
	}

	/* ------------------------------------------------------------ chat */
	const msgs = () => document.getElementById("dp-msgs");
	/* ------------------------------------------------- markdown rendering
	   Model output is UNTRUSTED, so the text is HTML-escaped FIRST and only tags
	   this function generates are ever inserted. That is why no sanitiser is
	   needed and why a general markdown library is not used here. */
	function mdInline(t) {
		t = t.replace(/`([^`]+)`/g, "<code>$1</code>");
		t = t.replace(/\*\*\*([^*]+)\*\*\*/g, "<strong><em>$1</em></strong>");
		t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
		t = t.replace(/__([^_]+)__/g, "<strong>$1</strong>");
		t = t.replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=[\s.,;:)!?]|$)/g, "$1<em>$2</em>");
		return t;
	}

	function renderMarkdown(src) {
		let text = esc(String(src == null ? "" : src));
		// pull fenced code out first so its contents are never treated as markup
		const blocks = [];
		text = text.replace(/```[a-z]*\n?([\s\S]*?)```/gi, (m, code) => {
			blocks.push(code.replace(/\n$/, ""));
			return "\u0000BLOCK" + (blocks.length - 1) + "\u0000";
		});

		const out = [];
		let list = null;          // "ul" | "ol" | null
		const closeList = () => { if (list) { out.push("</" + list + ">"); list = null; } };
		const para = [];
		const flushPara = () => {
			if (para.length) {
				out.push("<p>" + mdInline(para.join("<br>")) + "</p>");
				para.length = 0;
			}
		};

		text.split("\n").forEach((raw) => {
			const line = raw.replace(/\s+$/, "");
			if (!line.trim()) { flushPara(); closeList(); return; }

			let m = line.match(/^\s{0,3}(#{1,6})\s*(.+)$/);
			if (m) {
				flushPara(); closeList();
				out.push('<div class="mdh">' + mdInline(m[2]) + "</div>");
				return;
			}
			m = line.match(/^\s*&gt;\s?(.*)$/);          // "&gt;" — already escaped
			if (m) {
				flushPara(); closeList();
				out.push('<div class="mdq">' + mdInline(m[1]) + "</div>");
				return;
			}
			if (/^\s*\|[-\s|:]+\|\s*$/.test(line)) return;   // table separator row
			if (/^\s*\|.*\|\s*$/.test(line)) {                // table row -> compact line
				flushPara(); closeList();
				const cells = line.trim().replace(/^\||\|$/g, "").split("|")
					.map((c) => c.trim()).filter(Boolean);
				out.push('<span class="mdrow">' + mdInline(cells.join("  ·  ")) + "</span>");
				return;
			}
			m = line.match(/^\s*(?:[-*\u2022])\s+(.+)$/);
			if (m) {
				flushPara();
				if (list !== "ul") { closeList(); out.push("<ul>"); list = "ul"; }
				out.push("<li>" + mdInline(m[1]) + "</li>");
				return;
			}
			m = line.match(/^\s*\d+[.)]\s+(.+)$/);
			if (m) {
				flushPara();
				if (list !== "ol") { closeList(); out.push("<ol>"); list = "ol"; }
				out.push("<li>" + mdInline(m[1]) + "</li>");
				return;
			}
			if (list) closeList();
			para.push(line.trim());
		});
		flushPara(); closeList();

		let html = out.join("");
		blocks.forEach((code, i) => {
			html = html.replace("\u0000BLOCK" + i + "\u0000", "<pre>" + code + "</pre>");
		});
		// a <pre> that landed inside a <p> is invalid and browsers split the <p>
		return html.replace(/<p>(\s*<pre>)/g, "$1").replace(/(<\/pre>\s*)<\/p>/g, "$1");
	}

	// Replace a bubble's content with rendered markdown, leaving any appended
	// children (disclaimer / feedback row) to be added afterwards.
	function setRich(node, text) {
		if (!node) return node;
		node.classList.remove("provisional");
		node.innerHTML = "";
		const holder = el("div", { class: "dp-md" });
		holder.innerHTML = renderMarkdown(text);
		node.appendChild(holder);
		msgs() && (msgs().scrollTop = msgs().scrollHeight);
		return node;
	}

	// Markdown is for the eye, not the ear: strip it before speaking.
	function speakable(t) {
		return String(t || "")
			.replace(/```[\s\S]*?```/g, " ")
			.replace(/[*_`#>|]/g, "")
			.replace(/\s{2,}/g, " ")
			.trim();
	}

	function bubble(cls, text) {
		if (disabled || !msgs()) return el("div", {});   // torn down: swallow late writes
		const b = el("div", { class: "dp-b " + cls });
		b.textContent = text;
		msgs().appendChild(b);
		msgs().scrollTop = msgs().scrollHeight;
		return b;
	}
	function botSay(text) { const b = bubble("bot", text); if (live) speak(text); return b; }
	// Assistant prose goes through the renderer; user/system lines never do.
	function botSayRich(text, opts) {
		const b = bubble("bot", "");
		setRich(b, text);
		if (live && !(opts && opts.mute)) speak(text);
		return b;
	}
	function sysSay(text) { bubble("sys", text); }
	// Every generated answer carries the disclaimer: it is the model's reading of
	// the request, not a guarantee of how the ERP behaves. The report button turns
	// "that was wrong" into a pre-filled Issue instead of a lost complaint.
	const DISCLAIMER = "This is as the AI understood it \u2014 actual system behaviour may differ. "
		+ "Please verify before acting on it.";

	function addFeedback(bub, ref, question, answer) {
		if (!bub || typeof frappe === "undefined" || !frappe.call) return;
		const disc = el("div", { class: "dp-disc" });
		disc.textContent = DISCLAIMER;
		bub.appendChild(disc);

		const row = el("div", { class: "dp-fb" });
		row.innerHTML = '<span>Helpful?</span>'
			+ '<button data-fb="up" title="Yes">\u{1F44D}</button>'
			+ '<button data-fb="down" title="No">\u{1F44E}</button>'
			+ '<span class="sep">\u00b7</span>'
			+ '<button class="rep" data-fb="report">Still not resolved? Report an issue</button>';
		row.addEventListener("click", (e) => {
			const v = e.target.getAttribute("data-fb");
			if (!v) return;
			if (v === "report") return reportIssue(row, ref, question, answer);
			frappe.call({ method: "deskpilot.api.feedback",
				args: { ref: ref, helpful: v === "up" ? 1 : 0 } });
			row.innerHTML = "<span>Thanks \u2014 noted.</span>";
		});
		bub.appendChild(row);
	}

	// Ask for an optional "what went wrong", then file the Issue.
	function reportIssue(row, ref, question, answer) {
		const send = (note) => {
			row.innerHTML = "<span>Filing an issue\u2026</span>";
			frappe.call({
				method: "deskpilot.api.report_issue",
				args: {
					ref: ref, question: question || "", answer: answer || "",
					note: note || "", context: JSON.stringify(gatherContext()),
					session_id: getSid(),
				},
				callback: (r) => {
					const m = r.message || {};
					if (!m.ok) { row.innerHTML = ""; row.textContent = m.error || "Couldn't file the issue."; return; }
					row.innerHTML = "";
					const done = el("span", {});
					done.textContent = (m.duplicate ? "Already reported as " : "Issue ")
						+ m.name + " \u2014 the team has been notified. ";
					const link = el("button", { class: "rep" });
					link.textContent = "Open it";
					link.addEventListener("click", () => {
						try { frappe.set_route("Form", m.doctype, m.name); } catch (e) {}
					});
					row.appendChild(done); row.appendChild(link);
				},
				error: () => { row.innerHTML = ""; row.textContent = "Couldn't reach the server to file the issue."; },
			});
		};
		// frappe.prompt gives a proper Desk dialog; fall back to no note if absent.
		try {
			if (frappe.prompt) {
				frappe.prompt(
					[{ fieldname: "note", fieldtype: "Small Text", label: "What went wrong? (optional)",
					   description: "Your question, the answer and the current screen are attached automatically." }],
					(vals) => send(vals && vals.note), "Report an issue", "File issue");
				return;
			}
		} catch (e) {}
		send("");
	}

	/* ---------------------------------------------------- voice: output */
	function speak(text) {
		try {
			if (!window.speechSynthesis || !text) return;
			window.speechSynthesis.cancel();
			const u = new SpeechSynthesisUtterance(speakable(String(text).replace(/[🪄📎➤👋🟢🟡🎙💭🔊]/g, "")));
			u.rate = 1.03; u.pitch = 1.0;
			fab.classList.add("talking");           // mascot lips/rings animate
			if (live) setPhase("speaking");
			u.onend = () => { fab.classList.remove("talking"); onSpeechEnd(); };
			u.onerror = () => { fab.classList.remove("talking"); onSpeechEnd(); };
			window.speechSynthesis.speak(u);
		} catch (e) { fab.classList.remove("talking"); onSpeechEnd(); }
	}
	function onSpeechEnd() {
		setTimeout(() => {
			if (window.speechSynthesis && window.speechSynthesis.speaking) return;
			if (live) startListen();            // resume the conversation loop
			else setPhase("idle");              // back to gentle idle bob
		}, 250);
	}

	/* ----------------------------------------------------- voice: input */
	function liveBtn() { return panel.querySelector('[data-act=live]'); }
	function setPhase(p) {
		phase = p;
		// animate the mascot (talking is owned by speak()):
		fab.classList.remove("listening", "thinking");
		if (p === "listening") fab.classList.add("listening");
		else if (p === "thinking") fab.classList.add("thinking");
		const b = liveBtn(); if (!b) return;
		b.classList.remove("live-on", "listening", "speaking");
		if (!live) { setSub(); return; }
		b.classList.add("live-on");
		if (p === "listening") { b.classList.add("listening"); setSub("🎙 listening…"); }
		else if (p === "thinking") { setSub("💭 thinking…"); }
		else if (p === "speaking") { b.classList.add("speaking"); setSub("🔊 speaking…"); }
		else setSub("🟣 live — say something");
	}
	function toggleLive() {
		const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
		if (!SR) { sysSay("Voice not supported in this browser. Try Chrome/Edge."); return; }
		if (live) exitLive(); else enterLive();
	}
	function enterLive() {
		live = true;
		if (!state.open) openPanel();
		sysSay("Live mode on — I'm listening. Tap the wave again to stop.");
		startListen();
	}
	function exitLive() {
		live = false;
		try { recog && recog.abort(); } catch (e) {}
		if (window.speechSynthesis) window.speechSynthesis.cancel();
		setPhase("idle");
		sysSay("Live mode off.");
	}
	function startListen() {
		if (!live) return;
		const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
		if (!SR) return;
		try { recog && recog.abort(); } catch (e) {}
		recog = new SR();
		recog.lang = "en-US"; recog.interimResults = false; recog.maxAlternatives = 1; recog.continuous = false;
		recog.onstart = () => setPhase("listening");
		recog.onresult = (e) => {
			const t = (e.results[0][0].transcript || "").trim();
			if (!t) { return; }
			bubble("user", t);
			// Live voice batches too: speaking again mid-answer must not race the turn.
			if (inFlight) { queued.push(t); bubble("sys", "queued — answering next"); return; }
			setPhase("thinking");
			Promise.resolve(handle(t)).catch((err) => botSay("Error: " + err.message));
		};
		recog.onerror = (e) => {
			if (e.error === "not-allowed" || e.error === "service-not-allowed") {
				live = false; setPhase("idle"); sysSay("Microphone permission denied — enable it in the browser to use Live mode.");
			}
		};
		recog.onend = () => {
			// if we ended while still 'listening' (silence/no result) and still live, listen again
			if (live && phase === "listening") setTimeout(startListen, 300);
		};
		try { recog.start(); } catch (e) { setTimeout(startListen, 400); }
	}

	/* ------------------------------------------------------- attachments
	   No client-side text reading any more: the server extracts PDF/Word/Excel/
	   CSV/text/images with real parsers, permission-scoped, and the model pulls
	   the content on demand via the read_attachment tool. */
	const SUPPORTED_EXT = /\.(pdf|docx|xlsx|xlsm|png|jpe?g|webp|gif|bmp|txt|csv|tsv|json|md|log|xml|ya?ml|html?|js|py|sql|ini|cfg)$/i;

	function renderAtts() {
		const box = document.getElementById("dp-atts"); if (!box) return;
		box.innerHTML = "";
		attachments.forEach((a, i) => {
			const chip = el("div", { class: "dp-chip" });
			chip.innerHTML = `<span>📎</span><span class="nm"></span><span class="rm" data-rm="${i}">×</span>`;
			chip.querySelector(".nm").textContent = a.name;
			chip.title = a.name;
			box.appendChild(chip);
		});
	}
	function removeAtt(i) { attachments.splice(i, 1); renderAtts(); }

	function handleFile(file) {
		if (!file) return;
		if (file.size > MAX_UPLOAD_BYTES) {
			// Check before uploading: ERPNext would reject it anyway (System
			// Settings max_file_size = 10 MB), but only after the whole wait.
			return botSay(`"${file.name}" is ${(file.size / 1048576).toFixed(1)} MB — the limit is 10 MB.`);
		}
		if (!SUPPORTED_EXT.test(file.name || "")) {
			return botSay(`I can't read "${file.name}". I handle PDF, Word, Excel, images, and plain text/CSV/JSON.`);
		}
		const sizeKB = Math.round(file.size / 1024);
		bubble("user", `📎 ${file.name} (${sizeKB} KB)`);
		const status = bubble("bot typing", "uploading…");

		const fd = new FormData();
		fd.append("file", file, file.name);
		fd.append("is_private", 1);
		fd.append("optimize", 0);
		const headers = {};
		if (typeof frappe !== "undefined" && frappe.csrf_token) headers["X-Frappe-CSRF-Token"] = frappe.csrf_token;

		fetch("/api/method/upload_file", { method: "POST", headers, body: fd, credentials: "same-origin" })
			.then((r) => r.json().then((j) => ({ ok: r.ok, j })))
			.then(({ ok, j }) => {
				status.remove();
				if (!ok || !j || !j.message) {
					const msg = (j && (j._server_messages || j.exception)) || "upload failed";
					return botSay("Couldn't upload that file (" + String(msg).slice(0, 120) + ").");
				}
				const fdoc = j.message;
				attachments.push({ name: fdoc.file_name || file.name, type: file.type || "", url: fdoc.file_url });
				renderAtts();
				botSay(`Got "${fdoc.file_name || file.name}" ✓ — ask me anything about it.`);
			})
			.catch((e) => { status.remove(); botSay("Upload error: " + e.message); });
	}

	/* ------------------------------------------------------- UI control */
	// Preserve known all-caps acronyms when title-casing a doctype name, so
	// "POS Opening Entry" / "HRMS Payroll" stay navigable (Frappe resolution is
	// case-sensitive on the JS side: new_doc/module lookup).
	const ACRONYMS = new Set(["POS", "HRMS", "ESS", "CRM", "API", "ID", "SKU",
		"KSA", "UAE", "BHD", "VAT", "AP", "AR", "PO", "SO", "PI", "GRN", "POA"]);
	function titleCase(s) {
		return String(s || "").replace(/\w\S*/g, (w) => {
			const up = w.toUpperCase();
			if (ACRONYMS.has(up) || (up.length >= 2 && w === up)) return up;
			return w[0].toUpperCase() + w.slice(1).toLowerCase();
		});
	}
	const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

	// Every spotlight/walkthrough render is stamped with the generation that
	// requested it. clearSpot() bumps the generation, so a waitForRect() promise
	// that resolves AFTER the user dismissed the overlay can no longer re-show it.
	// That async race is what made "Done" appear not to work.
	let spotGen = 0;
	let spotAnchor = null;   // node the hole is currently glued to

	// Lay the four dismiss panels out so they tile the viewport EXCEPT the hole.
	function placeBackdrop(box) {
		const t = spot.querySelector(".bd-t"), r = spot.querySelector(".bd-r");
		const b = spot.querySelector(".bd-b"), l = spot.querySelector(".bd-l");
		const W = window.innerWidth, H = window.innerHeight;
		if (!box) {   // no anchor: one full-screen sheet (the top panel)
			t.style.cssText += ";left:0;top:0;width:" + W + "px;height:" + H + "px";
			[r, b, l].forEach((p) => { p.style.width = "0px"; p.style.height = "0px"; });
			return;
		}
		const x0 = Math.max(0, box.left), y0 = Math.max(0, box.top);
		const x1 = Math.min(W, box.left + box.width), y1 = Math.min(H, box.top + box.height);
		const set = (el2, L, T, Wd, Ht) => {
			el2.style.left = L + "px"; el2.style.top = T + "px";
			el2.style.width = Math.max(0, Wd) + "px"; el2.style.height = Math.max(0, Ht) + "px";
		};
		set(t, 0, 0, W, y0);                 // above
		set(b, 0, y1, W, H - y1);            // below
		set(l, 0, y0, x0, y1 - y0);          // left of
		set(r, x1, y0, W - x1, y1 - y0);     // right of
	}
	function placeHole(node, pad) {
		pad = pad == null ? 6 : pad;
		const hole = spot.querySelector(".hole");
		if (!node) { hole.style.display = "none"; placeBackdrop(null); return null; }
		const rr = node.getBoundingClientRect();
		hole.style.display = "block";
		hole.style.left = (rr.left - pad) + "px"; hole.style.top = (rr.top - pad) + "px";
		hole.style.width = (rr.width + pad * 2) + "px"; hole.style.height = (rr.height + pad * 2) + "px";
		placeBackdrop({ left: rr.left - pad, top: rr.top - pad,
			width: rr.width + pad * 2, height: rr.height + pad * 2 });
		return rr;
	}
	function clampTip(tip) {
		if (!tip) return;
		const r = tip.getBoundingClientRect();
		if (r.width < 2 || r.height < 2) return;   // still hidden: nothing to clamp
		const pad = 8;
		let top = r.top, left = r.left;
		top = Math.min(Math.max(pad, top), Math.max(pad, window.innerHeight - r.height - pad));
		left = Math.min(Math.max(pad, left), Math.max(pad, window.innerWidth - r.width - pad));
		if (Math.abs(top - r.top) > 1) tip.style.top = top + "px";
		if (Math.abs(left - r.left) > 1) tip.style.left = left + "px";
	}
	function placeTip(rr) {
		const tip = spot.querySelector(".tip");
		if (!rr) {
			tip.style.left = Math.max(12, window.innerWidth / 2 - 140) + "px";
			tip.style.top = (window.innerHeight / 2 - 60) + "px";
			return;
		}
		tip.style.left = Math.max(12, Math.min(rr.left, window.innerWidth - 280)) + "px";
		const top = rr.bottom + 12;
		tip.style.top = (top + 160 > window.innerHeight ? Math.max(12, rr.top - 120) : top) + "px";
		clampTip(tip);
	}
	function repositionSpot() {
		if (spot.style.display !== "block" || !spotAnchor) return;
		if (!document.body.contains(spotAnchor)) { clearSpot(); return; }
		placeTip(placeHole(spotAnchor));
	}

	function spotlight(node, title, desc) {
		if (!node) { botSay("I couldn't find that on the current screen."); return; }
		const gen = ++spotGen;
		// scroll_to_field already scrolls; a second scrollIntoView fights it.
		ensureVisible(node).then((res) => {
			if (gen !== spotGen) return;              // dismissed while we waited
			if (res !== "ok") {
				botSay(res === "hidden"
					? `"${title}" isn't shown on this form right now — it only appears in `
						+ `certain cases, so there's nothing on screen for me to point at.`
					: "That field is hidden or still loading — try again in a moment.");
				try {
					frappe.call({ method: "deskpilot.api.log_client",
						args: { kind: "spotlight_unresolved", detail: JSON.stringify({
							label: title, doctype: cur_frm && cur_frm.doctype,
							nodeAttached: !!(node && document.body.contains(node)),
							rect: (() => { const r = node.getBoundingClientRect();
								return [Math.round(r.width), Math.round(r.height)]; })() }) } });
				} catch (e) {}
				return;
			}
			spotAnchor = node;
			const rr = placeHole(node);
			const tip = spot.querySelector(".tip");
			tip.innerHTML = `<b>${esc(title || "Here")}</b>${esc(desc || "")}<br>`
				+ `<button data-act="spot-ok">Got it</button><span class="esc">or press Esc</span>`;
			placeTip(rr);
			spot.style.display = "block";
			clampTip(spot.querySelector(".tip"));
		});
	}
	function clearSpot() {
		spotGen++;              // invalidate anything still in flight
		spotAnchor = null;
		walk = null;
		spot.style.display = "none";
	}

	// ---- guided walkthrough (multi-step spotlight with Next) ----
	let walk = null;
	function spotlightStep(node, label, text, isLast, hint, hadTarget, diag) {
		/* hint may be replaced below once we know WHY a field could not be shown */
		const tip = spot.querySelector(".tip");
		const gen = ++spotGen;
		const render = (found) => {
			if (gen !== spotGen) return;          // superseded or dismissed mid-wait
			// Only cut a hole when the node ACTUALLY measured. Rendering regardless
			// drew the hole from a stale/zero rect.
			const anchor = found ? node : null;
			spotAnchor = anchor;
			const rr = placeHole(anchor);
			placeTip(rr);
			let tail = "";
			if (found) tail = hint ? `<span class="esc">${esc(hint)}</span>` : "";
			else if (hadTarget === false) tail = hint ? `<span class="esc">${esc(hint)}</span>` : "";
			else {
				tail = `<span class="esc">${esc(hint
					|| "I couldn't locate that field on screen — look for it by the label above.")}</span>`;
				// Silent until now: the node EXISTED but never got a stable, non-zero
				// rect, so the step degraded with nothing recorded anywhere.
				try {
					frappe.call({ method: "deskpilot.api.log_client",
						args: { kind: "spotlight_unresolved", detail: JSON.stringify({
							label: label, diag: diag || null, doctype: cur_frm && cur_frm.doctype,
							nodeAttached: !!(node && document.body.contains(node)),
							rect: node ? (() => { const r = node.getBoundingClientRect();
								return [Math.round(r.width), Math.round(r.height)]; })() : null,
							route: (frappe.get_route && frappe.get_route().join("/")) || "" }) } });
				} catch (e) {}
			}
			const body = esc(text) + tail;
			tip.innerHTML = `<b>${esc(label)}</b>${body}<br>`
				+ `<button data-act="walk-next">${isLast ? "Done" : "Next ▸"}</button>`
				+ `<span class="esc">Esc to exit</span>`;
			spot.style.display = "block";
			clampTip(spot.querySelector(".tip"));
			if (live) speak(text);
		};
		if (node) {
			ensureVisible(node).then((res) => {
				if (res === "hidden") hint = hint
					|| "This field isn't shown on this form right now — it only appears in "
					 + "certain cases. Carry on to the next step.";
				render(res === "ok");
			});
		} else render(false);
	}
	// The server resolved every step against args.for_doctype. Running them against
	// a DIFFERENT form — or none — is what produced ten consecutive "I couldn't
	// locate that field" steps with cur_frm null (measured 2026-08-19, a navigate
	// and a walkthrough emitted in the same turn). Wait for the right form, and
	// refuse rather than pretend to guide.
	function waitForFormDoctype(dt, timeout = 9000) {
		return new Promise((res) => {
			if (!dt) return res(true);
			const t0 = Date.now();
			(function poll() {
				if (typeof cur_frm !== "undefined" && cur_frm && cur_frm.fields_dict
					&& cur_frm.doctype === dt) return res(true);
				if (Date.now() - t0 > timeout) return res(false);
				setTimeout(poll, 200);
			})();
		});
	}
	function onExpectedForm(dt) {
		if (typeof cur_frm === "undefined" || !cur_frm || !cur_frm.fields_dict) return false;
		return !dt || cur_frm.doctype === dt;
	}
	async function runWalkthrough(args) {
		const steps = (args.steps || []).filter((s) => s && s.text);
		if (!steps.length) { botSay("I don't have steps for that walkthrough."); return; }
		const haveForm = typeof cur_frm !== "undefined" && cur_frm && cur_frm.fields_dict;
		if (args.needs_form && !haveForm) {
			botSay("There's no form open, so there's nothing for me to point at yet. "
				+ "Ask me to open the form first, then I'll walk you through it.");
			return;
		}
		if (!(await waitForFormDoctype(args.for_doctype))) {
			botSay(args.for_doctype
				? `I can't start that walkthrough — the ${args.for_doctype} isn't open on screen. `
					+ `Open it and ask me again.`
				: "There's no form open, so there's nothing for me to point at yet. "
					+ "Ask me to open the form first, then I'll walk you through it.");
			return;
		}
		let i = 0;
		walk = () => {
			// Left the form mid-walkthrough: stop, do not march through apologies.
			if (!onExpectedForm(args.for_doctype)) {
				clearSpot(); walk = null;
				const onSomeForm = typeof cur_frm !== "undefined" && cur_frm && cur_frm.fields_dict;
				botSay(onSomeForm
					? "We've moved to a different form, so I've stopped the walkthrough."
					: "There's no form open any more, so I've stopped the walkthrough.");
				return;
			}
			if (i >= steps.length) { clearSpot(); botSay("That's the walkthrough — you're all set."); return; }
			const s = steps[i];
			// Just the counter. The model's overall title ("How to make a Stock Entry")
			// repeated on EVERY step's tip and told the user nothing they had not
			// already read in the answer above.
			const label = `Step ${i + 1} of ${steps.length}`;
			const isLast = i === steps.length - 1;
			i++;
			let node = null, hint = null, hadTarget = false;
			if (s.fieldname || s.field || s.control) {
				hadTarget = true;
				// "add …" steps want the Add-row control, not the table body.
				const t = targetFromCanonical(s)
					|| resolveTarget(s.field, { preferAction: /\badd\b/i.test(s.text || "") });
				node = t.node; hint = t.hint;
				if (!node) {
					// Loud, not silent: an unresolvable step is a real gap in the
					// model's field naming and must be visible in telemetry.
					try {
						frappe.call({ method: "deskpilot.api.log_client",
							args: { kind: "walk_step_unresolved",
								detail: JSON.stringify({ field: s.field, doctype: cur_frm && cur_frm.doctype }) } });
					} catch (e) {}
				}
			}
			spotlightStep(node, label, s.text, isLast, hint, hadTarget,
				{ field: s.field || s.fieldname || s.control || null, grid: s.grid || null,
				  step: i, of: steps.length, want: args.for_doctype || null });
		};
		walk();
	}
	// Fields inside a collapsed section or an inactive tab have a zero-size rect,
	// so waitForRect times out and the user is told the field is "still loading".
	// Open the container first.
	// Which form field owns this node (a wrapper, or a cell inside a grid).
	function fieldnameForNode(node) {
		if (!node || typeof cur_frm === "undefined" || !cur_frm || !cur_frm.fields_dict) return null;
		for (const fn in cur_frm.fields_dict) {
			const f = cur_frm.fields_dict[fn];
			const w = f && f.$wrapper && f.$wrapper[0];
			if (w && (w === node || w.contains(node))) return fn;
		}
		return null;
	}
	// Make a field actually visible, using FRAPPE'S OWN machinery.
	//
	// Measured on a stock v16 new Sales Order: 95 of 162 fields have a zero-size rect.
	// 58 of them sit on an INACTIVE TAB, and others (currency, selling_price_list)
	// are inside a collapsed section whose body is hidden with `.section-body.hide`
	// — NOT `.form-section.collapsed`, which is what this function used to look for,
	// so it never opened them and the step reported "I couldn't locate that field".
	//
	// frm.scroll_to_field() is the canonical path: it calls section.collapse(false),
	// tab.set_active() and scrolls the field into view. Prefer it, then fall back to
	// those same APIs directly, then to DOM clicking.
	function revealField(node, fieldname) {
		if (!node) return;
		const fn = fieldname || fieldnameForNode(node);
		try {
			if (fn && cur_frm && typeof cur_frm.scroll_to_field === "function") {
				cur_frm.scroll_to_field(fn, false);   // no focus: we are pointing, not typing
				return;
			}
		} catch (e) {}
		revealHard(node, fn);
	}
	// Explicit second attempt, for when scroll_to_field is absent or did not settle.
	function revealHard(node, fieldname) {
		const fn = fieldname || fieldnameForNode(node);
		try {
			const f = fn && cur_frm && cur_frm.fields_dict[fn];
			if (f) {
				if (f.section && typeof f.section.is_collapsed === "function"
					&& f.section.is_collapsed() && typeof f.section.collapse === "function") {
					f.section.collapse(false);
				}
				if (f.tab && typeof f.tab.is_active === "function" && !f.tab.is_active()
					&& typeof f.tab.set_active === "function") {
					f.tab.set_active();
				}
			}
		} catch (e) {}
		if (!window.jQuery) return;
		try {
			const $n = window.jQuery(node);
			// Collapse is a `hide` class on the section BODY in v16; older builds put
			// `collapsed` on the section itself. Handle both.
			const $body = $n.closest(".section-body");
			if ($body.length && $body.hasClass("hide")) {
				$body.closest(".form-section").find(".section-head").first().click();
			}
			const $sec = $n.closest(".form-section");
			if ($sec.length && $sec.hasClass("collapsed")) $sec.find(".section-head").first().click();
			const $tabPane = $n.closest(".tab-pane");
			if ($tabPane.length && !$tabPane.hasClass("active")) {
				const id = $tabPane.attr("id");
				if (id) window.jQuery('.form-tabs a[href="#' + id + '"], [href="#' + id + '"]')
					.first().click();
			}
		} catch (e) {}
	}
	// One place that decides "is this pointable yet?" — reveal, wait briefly, try
	// harder, wait again, then give up. The old single 8s wait meant a miss made the
	// user sit through eight seconds after pressing Next before being told.
	// Returns "ok" | "hidden" | "missing". Measured on v16 after the reveal
	// rewrite: every reachable field — collapsed section OR inactive tab — settles in
	// ~130ms. The only genuine failure was `conversion_rate`, which the FORM marks
	// hidden at runtime (df.hidden is set live; the doctype meta says otherwise), and
	// polling for it cost 3.6s before giving up. Never poll for a field the form
	// itself says is not there.
	// "Visible" means ON SCREEN, not merely "has a non-zero rect". A field below the
	// fold measures a perfectly good rect, so an earlier version reported ok and drew
	// the hole off-screen — the user saw a dimmed page and a tip pointing at nothing.
	// Caught in a screenshot: the Add-row hole at y=1021 in a 905px viewport.
	function inViewport(node, margin) {
		const r = node.getBoundingClientRect();
		if (r.width < 2 || r.height < 2) return false;
		const m = margin == null ? 8 : margin;
		return r.top >= -m && r.bottom <= window.innerHeight + m;
	}
	async function ensureVisible(node) {
		if (!node) return "missing";
		const fn = fieldnameForNode(node);
		const f = fn && cur_frm && cur_frm.fields_dict[fn];
		if (f && f.df && f.df.hidden) return "hidden";
		revealField(node, fn);                      // expands section / activates tab
		let ok = await waitForRect(node, 2200);
		if (!ok) { revealHard(node, fn); ok = await waitForRect(node, 1400); }
		if (!ok) return (f && f.df && f.df.hidden) ? "hidden" : "missing";
		// It exists and is laid out — now make sure the user can actually SEE it.
		// scroll_to_field does not reliably scroll for every target (a grid's
		// add-row control among them), so scroll explicitly and re-settle.
		if (!inViewport(node)) {
			try { node.scrollIntoView({ block: "center", inline: "nearest" }); } catch (e) {}
			await waitForRect(node, 1200);
		}
		return "ok";
	}
	function findFieldByLabel(label, exactOnly) {
		if (typeof cur_frm === "undefined" || !cur_frm || !cur_frm.fields_dict) return null;
		const want = String(label).toLowerCase().trim();
		if (!want) return null;
		let exactFn = null, wordFn = null, partialFn = null;
		for (const fn in cur_frm.fields_dict) {
			const df = cur_frm.fields_dict[fn] && cur_frm.fields_dict[fn].df;
			if (!df) continue;
			const labelL = String(df.label || "").toLowerCase().trim();
			const nameL = String(df.fieldname || fn).toLowerCase();
			if (nameL === want || labelL === want) { if (!exactFn) exactFn = fn; }
			else if (!wordFn && (labelL.split(/\s+/).includes(want) || nameL.split(/\s+/).includes(want))) wordFn = fn;
			else if (!partialFn && (labelL.includes(want) || nameL.includes(want))) partialFn = fn;
		}
		if (exactOnly) return exactFn;
		return exactFn || wordFn || partialFn;
	}
	// Column labels carry qualifiers the model never says: "Rate (BHD)" must match
	// a request for "rate", and fieldname item_code must match "Item Code".
	function normLabel(x) {
		return String(x == null ? "" : x).toLowerCase()
			.replace(/\s*\([^)]*\)\s*/g, " ")     // drop "(BHD)", "(Company Currency)"
			.replace(/[_\s]+/g, " ").trim();
	}
	// The child doctype's columns. `df.fields` is UNDEFINED on v16 — measured on
	// Observed on v16 (Sales Order → items: df.fields undefined, df.options "Sales Order
	// Item", meta 115 fields) — which is why the grid fallback never once matched
	// and line items looked undiscoverable. The meta is the real source.
	function childFields(df) {
		if (Array.isArray(df.fields) && df.fields.length) return df.fields;
		try {
			const m = df.options && frappe.get_meta && frappe.get_meta(df.options);
			return (m && m.fields) || [];
		} catch (e) { return []; }
	}
	function findGridField(label, exactOnly) {
		if (typeof cur_frm === "undefined" || !cur_frm || !cur_frm.fields_dict) return null;
		const want = normLabel(label);
		if (!want) return null;
		let exact = null, partial = null;
		for (const fn in cur_frm.fields_dict) {
			const f = cur_frm.fields_dict[fn];
			const df = f && f.df;
			if (!df || df.fieldtype !== "Table") continue;
			for (const cdf of childFields(df)) {
				if (cdf.hidden) continue;
				const labelL = normLabel(cdf.label), nameL = normLabel(cdf.fieldname);
				const hit = { gridFn: fn, gridLabel: df.label, colLabel: cdf.label || cdf.fieldname,
					colFieldname: cdf.fieldname };
				if (nameL === want || labelL === want) { exact = exact || hit; }
				else if (!partial && want.length > 3
						&& (labelL.includes(want) || nameL.includes(want))) partial = hit;
			}
		}
		if (exactOnly) return exact;
		return exact || partial;
	}
	function fieldNode(fn) { const f = cur_frm && cur_frm.fields_dict[fn]; return f && f.$wrapper ? f.$wrapper[0] : null; }
	// Reach INSIDE a child table. Measured on v16 (Sales Order → items):
	// the grid renders `.grid-heading-row [data-fieldname]` header cells with real
	// rects (item_code, qty, rate, amount …) and a `.grid-add-row` button — so a
	// line-item column IS discoverable, it just was never looked for. Note the
	// meta route is NOT usable: df.fields filtered by `in_list_view` came back
	// EMPTY on this version, so the visible columns are read from the DOM.
	function gridColumnNode(gridFn, colFieldname) {
		const g = cur_frm && cur_frm.fields_dict[gridFn] && cur_frm.fields_dict[gridFn].grid;
		const w = g && g.wrapper && g.wrapper[0];
		if (!w || !colFieldname) return null;
		const cell = w.querySelector('.grid-heading-row [data-fieldname="' + colFieldname + '"]');
		if (cell && cell.getBoundingClientRect().width > 1) return cell;
		// Column exists in meta but is not shown in the row preview.
		return null;
	}
	function gridAddRowNode(gridFn) {
		const g = cur_frm && cur_frm.fields_dict[gridFn] && cur_frm.fields_dict[gridFn].grid;
		const w = g && g.wrapper && g.wrapper[0];
		const b = w && w.querySelector(".grid-add-row");
		return b && b.getBoundingClientRect().width > 1 ? b : null;
	}
	function gridRowCount(gridFn) {
		const g = cur_frm && cur_frm.fields_dict[gridFn] && cur_frm.fields_dict[gridFn].grid;
		return (g && g.grid_rows && g.grid_rows.length) || 0;
	}
	// The server resolves field names against frappe.get_meta and sends the
	// canonical target (fieldname + the grid it lives in). Prefer it: label
	// matching in the browser is a guess, this is not.
	function targetFromCanonical(a) {
		if (!a || typeof cur_frm === "undefined" || !cur_frm) return null;
		// An explicit control the server picked ("Add row"), not a field.
		if (a.control === "add_row" && a.grid) {
			const add = gridAddRowNode(a.grid);
			if (add) return { node: add, label: a.resolved_label || "Add row",
				hint: "Click it to add a line, then fill the columns." };
			return { node: fieldNode(a.grid), label: a.resolved_label || "Add row",
				hint: 'Use the "Add row" button in this table.' };
		}
		if (!a.fieldname) return null;
		if (a.grid) {
			const col = gridColumnNode(a.grid, a.fieldname);
			const gdf = cur_frm.fields_dict[a.grid] && cur_frm.fields_dict[a.grid].df;
			const gl = (gdf && gdf.label) || a.grid;
			const label = (a.resolved_label || a.fieldname);
			if (col) {
				return { node: col, label: gl + " → " + label,
					hint: gridRowCount(a.grid)
						? "Click the cell under this heading in the row below."
						: 'No lines yet — click "Add row" first, then fill this column.' };
			}
			const add = gridAddRowNode(a.grid);
			if (add) {
				return { node: add, label: gl + " → " + label,
					hint: '"' + label + '" lives on a line — click "Add row" first.' };
			}
			return { node: fieldNode(a.grid), label: gl + " → " + label,
				hint: '"' + label + '" is a column inside this table.' };
		}
		const n = fieldNode(a.fieldname);
		if (!n) return null;
		const df = cur_frm.fields_dict[a.fieldname].df;
		return { node: n, label: a.resolved_label || df.label, hint: null };
	}
	// THE resolver. Every spotlight caller (single highlight, walkthrough step)
	// goes through this, so a table stays reachable the same way everywhere.
	// Returns {node, label, hint} — node null only when nothing matched at all.
	function resolveTarget(label, opts) {
		opts = opts || {};
		// Order matters and was measured: a step for the line-item column
		// "Quantity" was being swallowed by the top-level "Total Quantity" field,
		// which spotlit the order total instead of the grid column. An exact
		// child-column match therefore outranks a fuzzy parent match.
		let fn = findFieldByLabel(label, true);
		let g = null;
		if (!fn) {
			g = findGridField(label, true);
			if (!g) fn = findFieldByLabel(label);
			if (!fn && !g) g = findGridField(label);
		}
		if (fn) {
			const df = cur_frm.fields_dict[fn].df;
			if (df.fieldtype === "Table") {
				// "Add the products being ordered" on an empty grid: the actionable
				// control is the Add-row button, not the empty table body.
				if (opts.preferAction || !gridRowCount(fn)) {
					const add = gridAddRowNode(fn);
					if (add) {
						return { node: add, label: df.label,
							hint: gridRowCount(fn)
								? 'Click "Add row" to add another line.'
								: 'The table is empty — click "Add row" to start a line.' };
					}
				}
				return { node: fieldNode(fn), label: df.label, hint: null };
			}
			return { node: fieldNode(fn), label: df.label, hint: null };
		}
		if (g) {
			// Point at the real column heading when the grid shows it.
			const col = gridColumnNode(g.gridFn, g.colFieldname);
			if (col) {
				return { node: col, label: g.gridLabel + " → " + g.colLabel,
					hint: gridRowCount(g.gridFn)
						? "Click the cell under this heading in the row below."
						: 'No lines yet — click "Add row" first, then fill this column.' };
			}
			const add = gridAddRowNode(g.gridFn);
			if (add && !gridRowCount(g.gridFn)) {
				return { node: add, label: g.gridLabel + " → " + g.colLabel,
					hint: '"' + g.colLabel + '" lives on a line — click "Add row" first.' };
			}
			return { node: fieldNode(g.gridFn), label: g.gridLabel + " → " + g.colLabel,
				hint: '"' + g.colLabel + '" is a column inside this table — click into a row to reach it.' };
		}
		return { node: null, label: label, hint: null };
	}
	function waitForForm(timeout = 5000) {
		return new Promise((res) => {
			const t0 = Date.now();
			(function poll() {
				if (typeof cur_frm !== "undefined" && cur_frm && cur_frm.fields_dict) return res(true);
				if (Date.now() - t0 > timeout) return res(false);
				setTimeout(poll, 200);
			})();
		});
	}
	// Wait until the node has a real (non-zero) AND settled bounding rect. The
	// field may still be rendering (async sections/forms) when the model replies,
	// and a rect read mid-scrollIntoView draws the hole in the wrong place — so
	// require two consecutive measurements within 2px before accepting.
	function waitForRect(node, timeout = 8000, step = 120) {
		return new Promise((res) => {
			const t0 = Date.now();
			let prev = null;
			(function poll() {
				if (!document.body.contains(node)) return res(false);
				const rr = node.getBoundingClientRect();
				if (rr.width > 1 && rr.height > 1) {
					if (prev && Math.abs(rr.top - prev.top) < 2 && Math.abs(rr.left - prev.left) < 2
						&& Math.abs(rr.width - prev.width) < 2 && Math.abs(rr.height - prev.height) < 2) {
						return res(true);
					}
					prev = { top: rr.top, left: rr.left, width: rr.width, height: rr.height };
				}
				if (Date.now() - t0 > timeout) return res(rr.width > 1 && rr.height > 1);
				setTimeout(poll, step);
			})();
		});
	}
	function doNavigate(a) {
		const dt = a.doctype ? titleCase(a.doctype) : "";
		if (a.filters && typeof frappe !== "undefined") frappe.route_options = a.filters;
		switch ((a.route_type || "list").toLowerCase()) {
			case "form": return frappe.set_route("Form", dt, a.name);
			case "new": return frappe.new_doc(dt);
			case "report": return frappe.set_route("List", dt, "Report");
			case "workspace": return frappe.set_route("Workspaces", a.doctype);
			default: return frappe.set_route("List", dt);
		}
	}
	function waitForRoute(target, timeout = 6000) {
		// set_route resolves on the route object; the page actually renders
		// after the route event fires, so wait for the target route pattern.
		return new Promise((res) => {
			const want = String(target || "").toLowerCase();
			const t0 = Date.now();
			(function poll() {
				const got = (frappe.get_route && frappe.get_route()) || [];
				const gotS = got.join("/").toLowerCase();
				const ok = want ? gotS.includes(want) : got.length > 0;
				if (ok) return res(got);
				if (Date.now() - t0 > timeout) return res(got);
				setTimeout(poll, 150);
			})();
		});
	}
	function doHighlight(a) {
		const t = targetFromCanonical(a) || resolveTarget(a.field_label);
		if (!t.node) return botSay(`I couldn't find a "${a.field_label}" field here.`);
		const fn = findFieldByLabel(a.field_label);
		const df = fn && cur_frm.fields_dict[fn].df;
		const body = a.description || (df && df.description)
			|| (t.hint ? "" : `This is the ${t.label} field.`);
		spotlight(t.node, a.title || t.label,
			[body, t.hint].filter(Boolean).join(" "));
	}
	function doFill(a) {
		// A child-table column cannot be set with cur_frm.set_value — say so rather
		// than silently setting nothing.
		if (a.grid) return botSay(`"${a.resolved_label || a.field_label}" is a column inside the `
			+ `${a.grid} table — open a row and set it there; I can't fill it directly.`);
		const fn = (a.fieldname && cur_frm.fields_dict[a.fieldname]) ? a.fieldname
			: findFieldByLabel(a.field_label);
		if (!fn) return botSay(`I couldn't find a "${a.field_label}" field to fill.`);
		cur_frm.set_value(fn, a.value);
		bubble("sys", `Set ${cur_frm.fields_dict[fn].df.label} → "${a.value}"`);
	}
	async function executeActions(actions) {
		for (const act of actions) {
			try {
				if (act.type === "navigate") {
				const route = (act.args && act.args.doctype) ? titleCase(act.args.doctype) : "";
				const p = doNavigate(act.args || {});
				if (p && p.then) await p;
				await waitForRoute(route);
				await sleep(150);
			}
				else if (act.type === "highlight_field") { await waitForForm(); await sleep(300); doHighlight(act.args || {}); }
				else if (act.type === "fill_field") { await waitForForm(); doFill(act.args || {}); }
				else if (act.type === "walkthrough") { await waitForForm(); await sleep(300); await runWalkthrough(act.args || {}); }
			} catch (e) { botSay("Couldn't run a UI action: " + e.message); }
			await sleep(150);
		}
	}

	/* ----------------------------------------------------- brain bridge */
	function gatherContext() {
		const ctx = { route: (frappe.get_route && frappe.get_route()) || [] };
		if (typeof cur_frm !== "undefined" && cur_frm) {
			ctx.doctype = cur_frm.doctype; ctx.docname = cur_frm.docname;
			// Only fields the user can actually SEE and name. Measured on a Sales
			// Order: of the 60 labels we used to send, 20 were Section Breaks or
			// hidden internals ("Name", "CC", "Series", "Idempotency Key"), while 39
			// genuinely useful fields never reached the model at all. Same token
			// budget, better content.
			const LAYOUT_FT = ["Section Break", "Column Break", "Tab Break", "HTML",
				"Heading", "Fold", "Button", "Image"];
			ctx.fields = Object.values(cur_frm.fields_dict)
				.filter((f) => f.df && f.df.label && !f.df.hidden
					&& LAYOUT_FT.indexOf(f.df.fieldtype) === -1)
				.map((f) => f.df.label).filter(Boolean).slice(0, 80);
			ctx.docstatus = (cur_frm.doc && cur_frm.doc.docstatus) || 0;
			// Line-item columns, so the model can NAME them. Without this it only
			// ever saw top-level labels and had to guess that "Item Code" exists —
			// a walkthrough step can only point at a column it knows about.
			// Bounded deliberately: 3 tables x 10 columns, labels only.
			ctx.tables = Object.values(cur_frm.fields_dict)
				.filter((f) => f.df && f.df.fieldtype === "Table" && !f.df.hidden)
				.slice(0, 3)
				.map((f) => ({
					table: f.df.label,
					columns: childFields(f.df).filter((c) => c.in_list_view || c.reqd)
						.map((c) => c.label || c.fieldname).filter(Boolean).slice(0, 10),
				}))
				.filter((t) => t.columns.length);
			ctx.missing_mandatory = Object.values(cur_frm.fields_dict)
				.filter((f) => f.df && f.df.reqd && cur_frm.doc && !cur_frm.doc[f.df.fieldname])
				.map((f) => f.df.label).filter(Boolean).slice(0, 30);
		}
		// Names/urls only — the model pulls contents on demand via read_attachment.
		if (attachments.length) ctx.attachments = attachments;
		return ctx;
	}
	// Enqueue the turn, then wait for the realtime push (with a polling fallback).
	// The old synchronous call was silently killed at 120s by nginx AND gunicorn.
	function sendBtn() { return panel.querySelector('[data-act=send]'); }
	function setBusy(on) {
		const b = sendBtn(); if (!b) return;
		b.classList.toggle("stop", !!on);
		b.innerHTML = on ? "\u25A0" : "\u27A4";
		b.title = on ? "Stop generating" : "Send";
	}
	// Tell the worker to stop, then settle locally so the UI frees up immediately
	// rather than waiting for the round trip.
	function stopGenerating() {
		const j = currentJob;
		if (!j) return;
		if (frappe.call) frappe.call({ method: "deskpilot.api.cancel", args: { job_id: j } });
		if (queued.length) { queued = []; bubble("sys", "stopped — queued messages discarded"); }
		settle({ job_id: j, cancelled: true, __local: true });
	}

	function newJobId() {
		let out = "";
		const abc = "abcdef0123456789";
		for (let i = 0; i < 24; i++) out += abc[Math.floor(Math.random() * abc.length)];
		return out;
	}
	function callBrain(text, typing) {
		// The job id is generated HERE and passed to the server, so the listener is
		// registered before the worker can emit anything. Previously the id only
		// came back in the response, which meant early chunks had nowhere to go and
		// forced a "use the only in-flight turn" guess — and that guess could route
		// one tab's stream into another tab, since events go to the user's room.
		const jobId = newJobId();
		currentJob = jobId;
		setBusy(true);
		const waiting = awaitReply(jobId, typing);
		return new Promise((res, rej) => {
			frappe.call({
				method: "deskpilot.api.ask",
				args: { message: text, context: JSON.stringify(gatherContext()),
					session_id: getSid(), job_id: jobId },
				callback: (r) => {
					const m = r.message || {};
					if (m.session_id) setSid(m.session_id);
					if (!m.job_id) { settle({ job_id: jobId, __drop: true }); return res({ r: m, ui: null }); }
					waiting.then(res);
				},
				error: (e) => { settle({ job_id: jobId, __drop: true }); rej(e); },
			});
		});
	}

	// One turn at a time per tab. Anything typed while a turn is running is
	// BATCHED and sent as a single follow-up when it finishes, instead of being
	// rejected by the server's per-session lock ("still working on your last
	// question") or racing it.
	let inFlight = false;
	let queued = [];

	function flushQueued() {
		if (inFlight || !queued.length) return;
		const batch = queued.join("\n");
		queued = [];
		Promise.resolve(handle(batch)).catch((e) => botSay("Error: " + e.message));
	}

	async function handle(text) {
		const t = text.trim(); if (!t) return;
		if (t.toLowerCase() === "help") return helpText();
		if (!brain || brain.provider === "none" || typeof frappe === "undefined" || !frappe.call) {
			botSay("I can't reach the model right now, so I can't answer this one. "
				+ "Please try again in a moment — if it keeps happening, tell IT.");
			return;
		}

		inFlight = true;
		const typing = bubble("bot typing", warmed ? "thinking…" : "waking the model — first reply can take up to a minute…");
		setPhase("thinking");
		try {
			const out = await callBrain(t, typing);
			const r = out.r || {}, ui = out.ui;
			if (typing.parentNode) typing.remove();
			// If a new bubble streamed, the retracted one is now a duplicate; drop it.
			// If nothing streamed, reuse it so the final text replaces it in place.
			if (ui && ui.retracted && ui.bubble && ui.bubble !== ui.retracted) {
				ui.retracted.remove();
				ui.retracted = null;
			}
			const streamBub = ui && (ui.bubble || ui.retracted);
			if (r.cancelled) {
				// Keep whatever was already streamed — the user saw it — and mark it.
				const partial = (r.text || (ui && ui.streamed) || "").trim();
				if (streamBub) {
					setRich(streamBub, partial || "_(stopped before anything was written)_");
				} else if (partial) {
					botSayRich(partial);
				}
				bubble("sys", "stopped");
			} else if (r.partial) {
				// Ran out of the server's time budget rather than being stopped.
				const partial = (r.text || (ui && ui.streamed) || "").trim();
				if (streamBub) setRich(streamBub, partial);
				else if (partial) botSayRich(partial);
				bubble("sys", "cut short — took too long. Try a narrower question.");
			} else if (r.rate_limited) {
				if (streamBub) streamBub.remove();
				botSay(r.error);
			} else if (r.error || r.provider === "none") {
				if (streamBub) streamBub.remove();
				botSay(r.error
					// The server now sends a plain-language reason; show it as-is rather
					// than wrapping a technical string in parentheses.
					? r.error
					: "The model isn't configured, so I can't answer that.");
			} else {
				warmed = true;
				let bub = null;
				// In talk mode a walkthrough SPEAKS each step, and speak() begins with
				// speechSynthesis.cancel() — so narrating the reply first meant the
				// answer was read aloud and then chopped off mid-sentence the moment
				// step 1 appeared. When steps are coming, they do the talking.
				const stepsWillSpeak = (r.actions || []).some(
					(a) => a && a.type === "walkthrough"
						&& ((a.args && a.args.steps) || []).some((st) => st && st.text));
				if (r.text) {
					if (streamBub) {
						setRich(streamBub, r.text); bub = streamBub;
						if (live && !stepsWillSpeak) speak(r.text);
					} else bub = botSayRich(r.text, { mute: stepsWillSpeak });
				} else if (streamBub) { streamBub.remove(); }
				if (r.actions && r.actions.length) await executeActions(r.actions);
				else if (!r.text) botSay("I didn't catch what you'd like me to do there. "
					+ "Try starting with a verb — for example \"open the employee advance balance "
					+ "list\" or \"walk me through this form\".");
				if (bub && r.id) addFeedback(bub, r.id, t, r.text);
			}
		} catch (e) {
			if (typing.parentNode) typing.remove();
			botSay("Couldn't reach the copilot service. Please try again in a moment.");
		}
		inFlight = false;
		currentJob = null;
		setBusy(false);
		// return mascot to rest (the live loop resumes itself on speech-end)
		if (!(window.speechSynthesis && window.speechSynthesis.speaking)) { if (live) startListen(); else setPhase("idle"); }
		flushQueued();
	}

	function helpText() {
		botSay("Examples:\n• \"open sales order list\" / \"show open sales orders\"\n• \"new customer\"\n• \"how many customers do we have?\"\n• \"highlight the customer field\" (on a form)\n• attach a PDF, Word, Excel, CSV or image, then \"summarise this\"\nI remember the conversation, so you can just say \"and the previous month?\".\nTap the wave button for hands-free voice.\nPress Esc (or the ■ button) to stop a reply mid-way; Esc also closes a spotlight.\n(Dismissed me with ✕? I stay as a faded outline in the corner — click me to come back.)");
	}

	/* -------------------------------------------- session history browser */
	const hist = () => document.getElementById("dp-hist");

	function toggleHistory() {
		const h = hist(); if (!h) return;
		if (h.classList.contains("open")) { h.classList.remove("open"); return; }
		h.classList.add("open");
		h.innerHTML = '<div class="empty">Loading…</div>';
		frappe.call({
			method: "deskpilot.api.list_sessions",
			callback: (r) => renderHistory((r.message || {}).sessions || []),
			error: () => { h.innerHTML = '<div class="empty">Couldn\u2019t load your conversations.</div>'; },
		});
	}

	function renderHistory(list) {
		const h = hist(); if (!h) return;
		h.innerHTML = "";
		const nw = el("div", { class: "newc" });
		nw.textContent = "＋  New conversation";
		nw.addEventListener("click", startNewSession);
		h.appendChild(nw);
		if (!list.length) {
			const e = el("div", { class: "empty" });
			e.textContent = "No earlier conversations yet.";
			h.appendChild(e);
			return;
		}
		const cur = getSid();
		list.forEach((sess) => {
			const row = el("div", { class: "hrow" + (sess.session_id === cur ? " cur" : "") });
			const t = el("div", { class: "ht" }); t.textContent = sess.title || "Conversation";
			const pv = el("div", { class: "hp" }); pv.textContent = sess.preview || "";
			const m = el("div", { class: "hm" });
			m.textContent = (sess.turns || 0) + (sess.turns === 1 ? " message" : " messages")
				+ " · " + relTime(sess.updated)
				+ (sess.session_id === cur ? " · current" : "");
			row.appendChild(t); row.appendChild(pv); row.appendChild(m);
			row.addEventListener("click", () => openSession(sess.session_id));
			h.appendChild(row);
		});
	}

	function relTime(ts) {
		if (!ts) return "";
		const secs = Math.max(0, Date.now() / 1000 - Number(ts));
		if (secs < 90) return "just now";
		if (secs < 3600) return Math.round(secs / 60) + "m ago";
		if (secs < 86400) return Math.round(secs / 3600) + "h ago";
		return Math.round(secs / 86400) + "d ago";
	}

	function startNewSession() {
		frappe.call({
			method: "deskpilot.api.new_session",
			callback: (r) => {
				const sid = (r.message || {}).session_id;
				if (sid) setSid(sid);
				attachments = []; renderAtts();
				msgs().innerHTML = "";
				hist().classList.remove("open");
				botSay("New conversation started.");
			},
			error: () => botSay("Couldn't start a new conversation."),
		});
	}

	// Re-render an earlier conversation and make it the active one, so the next
	// question continues it with the server-side history intact.
	function openSession(sid) {
		if (!sid) return;
		frappe.call({
			method: "deskpilot.api.load_session",
			args: { session_id: sid },
			callback: (r) => {
				const m = r.message || {};
				if (m.error) { botSay(m.error); return; }
				setSid(sid);
				attachments = []; renderAtts();
				msgs().innerHTML = "";
				(m.messages || []).forEach((x) => {
					if (x.role === "user") bubble("user", x.content);
					else setRich(bubble("bot", ""), x.content);
				});
				bubble("sys", "— resumed; ask anything to continue —");
				hist().classList.remove("open");
			},
			error: () => botSay("Couldn't open that conversation."),
		});
	}

	/* ------------------------------------------------------------ glue */
	function send() {
		const inp = document.getElementById("dp-in");
		const t = inp.value.trim(); if (!t) return;
		bubble("user", t); inp.value = ""; clearSpot();
		if (inFlight) {
			// Don't drop it and don't race the in-flight turn — batch it.
			queued.push(t);
			const n = queued.length;
			bubble("sys", n === 1 ? "queued — I'll answer this next"
				: "queued (" + n + ") — I'll answer these together");
			return;
		}
		Promise.resolve(handle(t)).catch((e) => botSay("Error: " + e.message));
	}
	function openPanel() { if (disabled) return; hideTip(); panel.classList.add("open"); state.open = true; save(); const i = document.getElementById("dp-in"); i && i.focus(); }
	function closePanel() { panel.classList.remove("open"); state.open = false; save(); }
	function dismissCopilot() {
		// Dormant, not deleted: the fab stays as a grey translucent outline that
		// colours in on hover. Clicking it wakes the copilot back up — no console needed.
		state.dismissed = true; state.open = false; save();
		panel.classList.remove("open"); hideTip();
		fab.classList.remove("hidden"); fab.classList.add("dismissed");
		fab.title = helperName + " — click to bring it back";
	}
	function restoreCopilot(open) {
		state.dismissed = false; save();
		fab.classList.remove("dismissed", "hidden");
		fab.title = helperName;
		if (open !== false) openPanel();
	}
	// Kept for support: window.deskpilot_show() also restores.
	window.deskpilot_show = () => restoreCopilot(true);

	/* -------------------------------------- proactive Clippy-style tips */
	let tipEl = null;
	function ensureTip() {
		if (tipEl) return tipEl;
		tipEl = el("div", { id: "dp-tip" });
		tipEl.addEventListener("click", (e) => {
			if (e.target.classList.contains("x")) { e.stopPropagation(); hideTip(); return; }
			openPanel();
		});
		document.body.appendChild(tipEl);
		return tipEl;
	}
	function showTip(html) {
		if (disabled || state.open || state.dismissed || live) return;
		const t = ensureTip();
		t.innerHTML = '<span class="x">×</span>' + html;
		t.style.display = "block";
		clearTimeout(t._to); t._to = setTimeout(hideTip, 9000);
	}
	function hideTip() { if (tipEl) tipEl.style.display = "none"; }
	function contextTip() {
		if (disabled || state.open || state.dismissed || live || typeof frappe === "undefined") return;
		const r = (frappe.get_route && frappe.get_route()) || [];
		const key = "dp_tip_" + r.join("/");
		if (sessionStorage.getItem(key)) return;
		let msg = null;
		if (r[0] === "Form" && typeof cur_frm !== "undefined" && cur_frm) {
			msg = `<b>Working on this ${esc(cur_frm.doctype)}?</b><br>Ask me to explain or fill a field, or where to go next.`;
		} else if (r[0] === "List" && r[1]) {
			msg = `<b>Looking through ${esc(r[1])}?</b><br>I can filter, count, or find records for you — just ask.`;
		} else if (!r.length || r[0] === "Workspaces" || r[0] === "workspace") {
			msg = `<b>I'm ${esc(helperName)}.</b><br>Ask me to open anything or answer a question about your data.`;
		}
		if (msg) { sessionStorage.setItem(key, "1"); showTip(msg); }
	}
	function bind() {
		fab.addEventListener("click", () => {
			if (state.dismissed) return restoreCopilot(true);   // wake from dormant
			state.open ? closePanel() : openPanel();
		});
		panel.addEventListener("click", (e) => {
			const rm = e.target.getAttribute && e.target.getAttribute("data-rm");
			if (rm !== null && rm !== undefined) { removeAtt(parseInt(rm, 10)); return; }
			const node = e.target.closest && e.target.closest("[data-act]");
			if (!node) return;
			const act = node.getAttribute("data-act");
			// The minimise button was removed: ✕ already closes the panel and the
			// fab stays on screen as a faded outline, so the two did the same job.
			if (act === "hist") toggleHistory();
			else if (act === "dismiss") dismissCopilot();
			else if (act === "send") { if (inFlight) stopGenerating(); else send(); }
			else if (act === "live") toggleLive();
			else if (act === "attach") document.getElementById("dp-file").click();
		});
		document.getElementById("dp-in").addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
		document.getElementById("dp-file").addEventListener("change", (e) => { const f = e.target.files[0]; handleFile(f); e.target.value = ""; });
		spot.addEventListener("click", (e) => {
			const a = e.target.getAttribute("data-act");
			if (a === "walk-next") { if (walk) walk(); return; }
			// .backdrop is a real pointer-events:auto layer now, so clicking
			// outside the tip genuinely dismisses.
			if (a === "spot-ok" || e.target.classList.contains("backdrop") || e.target.id === "dp-spot") clearSpot();
		});
	}

	/* --------------------------------------------------------- helpers */
	function esc(s) { return String(s == null ? "" : s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }
	function el(tag, opts) {
		const n = document.createElement(tag); opts = opts || {};
		if (opts.id) n.id = opts.id;
		if (opts.class) n.className = opts.class;
		if (opts.title) n.title = opts.title;
		if (opts.html != null) n.innerHTML = opts.html;
		return n;
	}

	if (document.body) mount();
	else document.addEventListener("DOMContentLoaded", mount);
})();
