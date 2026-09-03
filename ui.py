"""Local browser UI for live invoice processing and offline recovery."""

import argparse
import copy
import json
import os
import threading
import webbrowser
from contextlib import ExitStack
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from dotenv import load_dotenv
from xai_sdk import Client

from configuration import DEFAULT_CONFIG_PATH, load_config
from main import OUTCOME_LABELS, process_folder, process_invoice
from offline import OfflineClient
from operational_logging import log_event, log_run
from reporting import write_report
from setup_inventory import OFFLINE_DATABASE_PATH
from workflow import build_workflow


ROOT = Path(__file__).resolve().parent
DEFAULT_INVOICE_DIR = ROOT / "data" / "invoices"
RUNS: dict[str, dict] = {}
RUNS_LOCK = threading.Lock()


def make_graph(client, settings, *, offline: bool):
    return build_workflow(
        client,
        "offline-simulation" if offline else os.getenv("XAI_MODEL") or settings.model.name,
        reasoning_effort=settings.model.reasoning_effort,
        dollar_policy=settings.currency.unqualified_dollar,
        approval_settings=settings.approval,
        inventory_aliases=settings.inventory.aliases,
        **({"database_path": OFFLINE_DATABASE_PATH} if offline else {}),
    )


def update_run(run_id: str, **values) -> None:
    with RUNS_LOCK:
        RUNS[run_id].update(values)


def add_notice(run_id: str, message: str) -> None:
    with RUNS_LOCK:
        RUNS[run_id]["notices"].append(message)


def run_invoices(run_id: str, directory: Path) -> None:
    try:
        settings = load_config(DEFAULT_CONFIG_PATH)
        paths = sorted((path for path in directory.iterdir() if path.is_file()),
                       key=lambda path: (path.name.casefold(), path.name))
        if not paths:
            raise ValueError("The selected directory contains no files.")
        update_run(run_id, status="running", total=len(paths))
        load_dotenv(ROOT / ".env", encoding="utf-8-sig")
        api_key = os.getenv("XAI_API_KEY", "").strip()
        fallback_active = threading.Event()
        if not api_key:
            fallback_active.set()
            add_notice(run_id, "No xAI API key was found. Continuing with offline fixtures.")

        with log_run(ROOT / "logs") as (_, log_path), ExitStack() as stack:
            update_run(run_id, log_path=str(log_path))
            offline_graph = make_graph(OfflineClient(), settings, offline=True)
            live_graph = None
            if api_key:
                live_client = stack.enter_context(Client(api_key=api_key, timeout=settings.model.timeout_seconds))
                live_graph = make_graph(live_client, settings, offline=False)

            def process(path: Path):
                if fallback_active.is_set():
                    return process_invoice(offline_graph, path)
                result, code = process_invoice(live_graph, path)
                error = result.get("error", "")
                if result["outcome"] == "processing_error" and "Grok API" in error:
                    fallback_active.set()
                    add_notice(run_id, "The Grok API became unavailable. Retrying affected invoices and continuing offline.")
                    result, code = process_invoice(offline_graph, path)
                    result["recovery"] = "Retried offline after the Grok API request failed."
                return result, code

            def completed(item: dict) -> None:
                with RUNS_LOCK:
                    RUNS[run_id]["results"].append(item)
                    RUNS[run_id]["completed"] += 1

            output = process_folder(live_graph or offline_graph, paths, settings.batch.workers,
                                    on_result=completed, process=process)
            report_path = ROOT / "logs" / f"invoice-report-{run_id}.html"
            write_report(output, report_path)
            log_event("ui_run_result", file_count=len(paths), fallback_used=fallback_active.is_set())
            update_run(run_id, status="complete", summary=output["summary"],
                       report_path=str(report_path), mode="offline" if fallback_active.is_set() else "live")
    except Exception as error:
        update_run(run_id, status="failed", error=str(error))


def start_run(directory_value: str) -> dict:
    directory = Path(directory_value).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError("Choose an existing invoice directory.")
    run_id = str(uuid4())
    with RUNS_LOCK:
        RUNS[run_id] = {"id": run_id, "status": "starting", "directory": str(directory),
                        "created_at": datetime.now(timezone.utc).isoformat(), "total": 0,
                        "completed": 0, "results": [], "notices": [], "summary": None,
                        "report_path": None, "log_path": None, "mode": "live", "error": None}
    threading.Thread(target=run_invoices, args=(run_id, directory), daemon=True).start()
    return {"run_id": run_id}


HTML = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>InvoiceFlow</title><style>
body{margin:0;background:#f3f6fa;color:#172538;font:16px/1.5 system-ui,sans-serif}main{max-width:1100px;margin:36px auto;padding:0 24px}
.eyebrow{color:#285579;font-weight:700;letter-spacing:.12em;font-size:12px}h1{margin:4px 0}.panel,.result,.notice{background:#fff;border-radius:12px;padding:20px;margin:18px 0;box-shadow:0 2px 12px #17324d12}
label{display:block;font-weight:700;margin-bottom:6px}.row{display:flex;gap:10px}input{flex:1;padding:11px;border:1px solid #aebbc9;border-radius:7px}button,a.button{background:#285579;color:#fff;border:0;border-radius:7px;padding:11px 16px;cursor:pointer;text-decoration:none}
button:disabled{opacity:.5}.notice{background:#fff3cd}.progress{height:10px;background:#dbe3eb;border-radius:8px;overflow:hidden}.bar{height:100%;background:#287a63;width:0;transition:width .25s}.meta{color:#52647a;font-size:14px}.badge{display:inline-block;padding:3px 9px;border-radius:6px;background:#e8eef5;font-size:13px;font-weight:700}.simulated_paid,.already_paid{background:#dcf3e7;color:#18583c}.pending_approval,.payment_held{background:#fff0cc;color:#725000}.processing_error,.rejected,.validation_blocked{background:#fce4e4;color:#832b2b}details{margin-top:14px}summary{cursor:pointer;color:#285579;font-weight:700}details li{margin:6px 0}
</style></head><body><main><div class="eyebrow">ACME CORP · INVOICEFLOW</div><h1>Process invoices</h1><p>Select a local directory. Results appear as each invoice completes.</p>
<section class="panel"><label for="directory">Invoice directory</label><div class="row"><input id="directory" value="__DEFAULT__"><button id="browse" type="button">Browse</button><button id="run" type="button">Process</button></div></section>
<section id="status" hidden><p id="statusText"></p><div class="progress"><div class="bar" id="bar"></div></div><div id="notices"></div><div id="results"></div><p><a class="button" id="report" hidden>Open completed report</a></p></section>
<script>
const q=id=>document.getElementById(id); let timer, shown=0;
q('browse').onclick=async()=>{const r=await fetch('/api/select-directory',{method:'POST'});const d=await r.json();if(d.directory)q('directory').value=d.directory;else if(d.error)alert(d.error)};
q('run').onclick=async()=>{q('run').disabled=true;shown=0;q('results').replaceChildren();q('notices').replaceChildren();q('report').hidden=true;const r=await fetch('/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({directory:q('directory').value})});const d=await r.json();if(!r.ok){alert(d.error);q('run').disabled=false;return}q('status').hidden=false;timer=setInterval(()=>poll(d.run_id),500);poll(d.run_id)};
async function poll(id){const r=await fetch('/api/runs/'+id);const d=await r.json();q('statusText').textContent=`${d.status} · ${d.completed}/${d.total} · ${d.mode}`;q('bar').style.width=(d.total?100*d.completed/d.total:0)+'%';q('notices').replaceChildren(...d.notices.map(n=>{const e=document.createElement('div');e.className='notice';e.textContent=n;return e}));
for(;shown<d.results.length;shown++){const x=d.results[shown],inv=x.invoice||{},e=document.createElement('article');e.className='result';const h=document.createElement('h3');h.textContent=inv.invoice_number||x.invoice_path;const b=document.createElement('span');b.className='badge '+x.outcome;b.textContent=x.outcome.replaceAll('_',' ');const p=document.createElement('p');p.className='meta';p.textContent=[inv.vendor,inv.amount,inv.currency].filter(Boolean).join(' · ');const messages=[];if(x.recovery)messages.push(x.recovery);if(x.error)messages.push(x.error);messages.push(...(x.validation_issues||[]));const approval=(x.processing.approval||{}).reason;if(!messages.length&&approval)messages.push(approval);if(!messages.length)messages.push('Completed');const details=document.createElement('details'),summary=document.createElement('summary'),list=document.createElement('ul');summary.textContent='View errors and details';for(const message of messages){const item=document.createElement('li');item.textContent=message;list.append(item)}details.append(summary,list);e.append(h,b,p,details);q('results').append(e)}
if(d.status==='complete'||d.status==='failed'){clearInterval(timer);q('run').disabled=false;if(d.error){const e=document.createElement('div');e.className='notice';e.textContent=d.error;q('notices').append(e)}if(d.report_path){q('report').href='/report/'+id;q('report').hidden=false}}}
</script></main></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def send_json(self, value, status=200):
        body = json.dumps(value).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            body = HTML.replace("__DEFAULT__", escape(str(DEFAULT_INVOICE_DIR), quote=True)).encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path.startswith("/api/runs/"):
            run_id = path.rsplit("/", 1)[-1]
            with RUNS_LOCK: run = copy.deepcopy(RUNS.get(run_id, {}))
            self.send_json(run or {"error": "Run not found."}, 200 if run else 404); return
        if path.startswith("/report/"):
            run_id = path.rsplit("/", 1)[-1]
            with RUNS_LOCK: report = RUNS.get(run_id, {}).get("report_path")
            if report and Path(report).is_file():
                body = Path(report).read_bytes(); self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        self.send_json({"error": "Not found."}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/runs":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                value = json.loads(self.rfile.read(length) or b"{}")
                self.send_json(start_run(value.get("directory") or str(DEFAULT_INVOICE_DIR)), 202)
            except (ValueError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error)}, 400)
            return
        if path == "/api/select-directory":
            try:
                from tkinter import Tk, filedialog
                root = Tk(); root.withdraw(); root.attributes("-topmost", True)
                directory = filedialog.askdirectory(initialdir=DEFAULT_INVOICE_DIR); root.destroy()
                self.send_json({"directory": directory})
            except Exception:
                self.send_json({"error": "The system directory picker is unavailable; enter a path instead."}, 503)
            return
        self.send_json({"error": "Not found."}, 404)

    def log_message(self, format, *args):
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local InvoiceFlow browser UI.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"InvoiceFlow UI: {url}", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nInvoiceFlow UI stopped.")


if __name__ == "__main__":
    main()
