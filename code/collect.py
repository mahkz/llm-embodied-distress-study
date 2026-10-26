"""
Collect chatbot responses to bodily-emotional distress scenarios, via OpenRouter.

What this script does:
  1. Reads the scenarios from scenarios.csv.
  2. Sends each scenario to each model (OpenAI, Anthropic, Google) through OpenRouter,
     several times (RUNS_PER_SCENARIO).
  3. Saves every response, with its details, as one row in responses.csv.
  4. If stopped, running it again continues from where it stopped.

Usage:
  python collect.py --dry-run     # no API calls; writes fake responses to test the pipeline
  python collect.py               # real run

The API key is read from an environment variable, never written in the code:
  OPENROUTER_API_KEY
"""

import argparse
import csv
import os
import time
from datetime import datetime, timezone

# ---------------------------------------------------------------
# 1. Settings: change these, not the code below
# ---------------------------------------------------------------

# Exact OpenRouter model IDs. Use fixed versions, never "latest" aliases.
MODELS = {
    "openai": "openai/gpt-6.1-sol",
    "anthropic": "anthropic/claude-sonnet-5.5",
    "google": "google/gemini-3.8-flash",
}

RUNS_PER_SCENARIO = 3
TEMPERATURE = 1.0          # same value for all models; recorded in the output
MAX_TOKENS = 3000          # generous limit so answers are not cut off (recorded in finish_reason)
PAUSE_SECONDS = 1.0        # short pause between calls
MAX_RETRIES = 4            # if a call hits a temporary error, wait and try again
RETRY_WAIT_SECONDS = 20    # first wait; doubles after each failed retry

SCENARIOS_FILE = "scenarios.csv"
OUTPUT_FILE = "responses.csv"

# No system prompt: each model sees only the user's message,
# like a first message in a new chat.


# ---------------------------------------------------------------
# 2. One function sends one message to one model through OpenRouter
# ---------------------------------------------------------------

_client = None


def get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ["OPENROUTER_API_KEY"],
        )
    return _client


def ask(model_id, message):
    """Returns (response text, model that answered, host provider that served it)."""
    response = get_client().chat.completions.create(
        model=model_id,
        messages=[{"role": "user", "content": message}],
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        # Keep the model's internal reasoning out of the answer text.
        extra_body={"reasoning": {"exclude": True}},
    )
    choice = response.choices[0]
    text = choice.message.content or ""
    extra = getattr(response, "model_extra", None) or {}
    host = extra.get("provider", "")
    usage = response.usage
    info = {
        "finish_reason": choice.finish_reason or "",
        "prompt_tokens": getattr(usage, "prompt_tokens", "") if usage else "",
        "completion_tokens": getattr(usage, "completion_tokens", "") if usage else "",
    }
    return text, response.model, host, info


def fake_ask(model_id, message):
    """Used in --dry-run mode, so the pipeline can be tested without an API key."""
    return (f"[DRY RUN] fake response to: {message[:40]}", "dry-run-model", "dry-run-host",
            {"finish_reason": "stop", "prompt_tokens": 0, "completion_tokens": 0})


class StopRun(Exception):
    pass


def is_temporary_error(e):
    """Rate limits (429) and temporary server problems (500/502/503) are worth retrying."""
    text = str(e)
    return any(code in text for code in ["429", "500", "502", "503", "UNAVAILABLE", "overloaded", "rate limit"])


def call_with_retries(function, model_id, message, dry_run):
    """Call the model; on a temporary error, wait and try again. Returns (text, model, host, info, error)."""
    wait = RETRY_WAIT_SECONDS
    for attempt in range(MAX_RETRIES + 1):
        try:
            text, model_returned, host, info = function(model_id, message)
            if not text.strip():
                raise ValueError("empty response")
            return text, model_returned, host, info, ""
        except Exception as e:
            if "402" in str(e) or "insufficient credits" in str(e).lower():
                raise StopRun(str(e))  # out of credit: stop the whole run
            if attempt < MAX_RETRIES and is_temporary_error(e) and not dry_run:
                print(f"    temporary error, waiting {wait} s and retrying ({attempt + 1}/{MAX_RETRIES})")
                time.sleep(wait)
                wait *= 2
            else:
                return "", "", "", {}, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------
# 3. Main loop
# ---------------------------------------------------------------

def load_scenarios(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="do not call any API; write fake responses")
    parser.add_argument("--include-pending", action="store_true",
                        help="also run scenarios whose status is 'pending'")
    args = parser.parse_args()

    scenarios = load_scenarios(SCENARIOS_FILE)
    if not args.include_pending:
        skipped = [s for s in scenarios if s["status"] != "final"]
        scenarios = [s for s in scenarios if s["status"] == "final"]
        for s in skipped:
            print(f"Skipping {s['scenario_id']}-{s['language']} (status: {s['status']})")

    if not args.dry_run and not os.environ.get("OPENROUTER_API_KEY"):
        print('No OPENROUTER_API_KEY found. Set it with: export OPENROUTER_API_KEY="..."')
        return

    active = []
    for provider, model_id in MODELS.items():
        if model_id.startswith("PUT-"):
            print(f"No model ID set for {provider}: skipping it (edit MODELS at the top of the file)")
        else:
            active.append((provider, model_id))
    if not active:
        print("No models to run.")
        return

    function = fake_ask if args.dry_run else ask

    fieldnames = ["timestamp_utc", "provider", "model_requested", "model_returned", "host",
                  "scenario_id", "type", "language", "run", "temperature", "max_tokens",
                  "finish_reason", "prompt_tokens", "completion_tokens",
                  "prompt", "response", "error"]

    # Resume: keep only successful rows from earlier runs, and skip those calls.
    completed = set()
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            old_rows = list(csv.DictReader(f))
        good_rows = [r for r in old_rows if r.get("response") and not r.get("error")]
        dropped = len(old_rows) - len(good_rows)
        with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            w.writerows(good_rows)
        completed = {(r["model_requested"], r["scenario_id"], r["language"], str(r["run"])) for r in good_rows}
        print(f"Found {len(good_rows)} successful responses from earlier runs"
              + (f"; removed {dropped} failed rows to retry them" if dropped else ""))

    file_exists = os.path.exists(OUTPUT_FILE)
    with open(OUTPUT_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()

        total = len(active) * len(scenarios) * RUNS_PER_SCENARIO
        done = 0
        stop = False
        for provider, model_id in active:
            if stop:
                break
            for s in scenarios:
                if stop:
                    break
                for run in range(1, RUNS_PER_SCENARIO + 1):
                    done += 1
                    requested = "dry-run" if args.dry_run else model_id
                    if (requested, s["scenario_id"], s["language"], str(run)) in completed:
                        print(f"[{done}/{total}] {provider} {s['scenario_id']}-{s['language']} run {run} already done, skipping")
                        continue
                    try:
                        text, model_returned, host, info, error = call_with_retries(
                            function, model_id, s["text"], args.dry_run)
                    except StopRun as e:
                        print(f"\nStopped: {str(e)[:200]}")
                        print("Check your OpenRouter credit. Everything so far is saved; run again to continue.")
                        stop = True
                        break
                    writer.writerow({
                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                        "provider": provider,
                        "model_requested": requested,
                        "model_returned": model_returned,
                        "host": host,
                        "scenario_id": s["scenario_id"],
                        "type": s["type"],
                        "language": s["language"],
                        "run": run,
                        "temperature": TEMPERATURE,
                        "max_tokens": MAX_TOKENS,
                        "finish_reason": info.get("finish_reason", ""),
                        "prompt_tokens": info.get("prompt_tokens", ""),
                        "completion_tokens": info.get("completion_tokens", ""),
                        "prompt": s["text"],
                        "response": text,
                        "error": error,
                    })
                    f.flush()  # save after every call, so nothing is lost if it stops
                    cut = info.get("finish_reason") == "length"
                    print(f"[{done}/{total}] {provider} {s['scenario_id']}-{s['language']} run {run}"
                          + (" ERROR" if error else "") + (" CUT OFF (raise MAX_TOKENS)" if cut else ""))
                    if not args.dry_run:
                        time.sleep(PAUSE_SECONDS)

    print(f"Done. Responses saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
