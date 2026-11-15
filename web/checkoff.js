"use strict";

function topicsForRequest(path, data) {
  const route = path.split("?")[0];
  const topics =
    route === "/upload"
      ? ["upload", "storage", "cache"]
      : route === "/movies/search"
        ? ["search"]
        : route === "/movies/process"
          ? ["processing", "validation", "outliers", "missing", "cache"]
          : route === "/movies"
            ? ["retrieve", "cache"]
            : ["health"];
  if (data && typeof data === "object" && "detail" in data)
    topics.unshift("errors");
  return [...new Set(topics)];
}

function codeLinks(container, topics) {
  container.replaceChildren();
  topics.forEach((topic) => {
    const link = document.createElement("a");
    link.href = `/ui/source/${encodeURIComponent(topic)}`;
    link.dataset.source = topic;
    link.textContent = state.topics[topic] || topic;
    container.append(link);
  });
}

async function showSource(topic) {
  const dialog = byId("source-dialog");
  dialog.scrollTop = 0;
  byId("source-title").textContent = "Loading related code…";
  byId("source-explanation").textContent = "";
  byId("source-content").replaceChildren();
  if (!dialog.open) dialog.showModal();
  try {
    const response = await fetch(`/ui/source/${encodeURIComponent(topic)}`, {
      cache: "no-store",
    });
    const source = await response.json();
    if (!response.ok)
      throw new Error(source.detail || "Code reference unavailable.");
    byId("source-title").textContent = source.title;
    byId("source-explanation").textContent = source.explanation;
    source.sources.forEach((reference) => {
      const section = document.createElement("section");
      section.className = "source-section";
      const heading = document.createElement("h3");
      heading.textContent = `${reference.file}:${reference.start_line} — ${reference.symbol}`;
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      code.textContent = reference.lines
        .map((line) => `${String(line.number).padStart(4)}  ${line.text}`)
        .join("\n");
      pre.append(code);
      section.append(heading, pre);
      byId("source-content").append(section);
    });
  } catch (error) {
    byId("source-title").textContent = "Code reference unavailable";
    byId("source-explanation").textContent = error.message;
  }
}

function requestBodyDescription(options) {
  if (options.body instanceof FormData) {
    return (
      Array.from(options.body.entries(), ([key, value]) =>
        value instanceof File
          ? `${key}: filename=${value.name}, bytes=${value.size}, content-type=${value.type || "unspecified"}`
          : `${key}: ${value}`,
      ).join("\n") || "Empty multipart form"
    );
  }
  return options.body ?? "No request body";
}

function inspectRequest(event) {
  byId("request-inspector").hidden = false;
  byId("response-status").textContent = `HTTP ${event.status}`;
  byId("response-status").className = event.ok ? "" : "response-error";
  byId("response-meta").textContent =
    `${event.method} ${event.path} · ${event.duration} ms · request_id=${event.requestId || "unavailable"}`;
  byId("sent-request").textContent =
    `${event.method} ${event.path}\n${Object.entries(
      event.options.headers || {},
    )
      .map(([key, value]) => `${key}: ${value}`)
      .join("\n")}\n${event.sentBody}`;
  byId("response-body").textContent =
    typeof event.data === "object"
      ? JSON.stringify(event.data, null, 2)
      : event.rawResponse;
  byId("response-headers").textContent = Object.entries(event.headers)
    .map(([key, value]) => `${key}: ${value}`)
    .join("\n");
  byId("server-logs").textContent = event.logsText;
  byId("response-details").open = !event.ok;
  byId("server-log-details").open = !event.ok;
  codeLinks(
    byId("request-code-links"),
    topicsForRequest(event.path, event.data),
  );
  if (!event.ok) byId("request-inspector").scrollIntoView({ block: "start" });
}

async function recordRequest(event) {
  event.sentBody = requestBodyDescription(event.options);
  event.options = { headers: event.options.headers || {} };
  event.time = new Date().toLocaleTimeString("en-US", { hour12: false });
  event.logsText = "Related logs unavailable.";
  if (event.requestId) {
    try {
      const response = await fetch(
        `/ui/requests/${encodeURIComponent(event.requestId)}`,
        { cache: "no-store" },
      );
      const journal = await response.json();
      event.logsText = response.ok
        ? journal.logs
            .map((entry) => {
              const time = new Date(entry.timestamp * 1000).toLocaleTimeString(
                "en-US",
                { hour12: false },
              );
              return `${time} ${entry.level} ${entry.logger}${entry.file ? ` (${entry.file}:${entry.line})` : ""}\n${entry.message}${entry.traceback ? `\n${entry.traceback}` : ""}`;
            })
            .join("\n\n") ||
          "No application log records were emitted for this request."
        : journal.detail || "Logs expired.";
    } catch {
      event.logsText =
        "Could not retrieve related server logs. The server may have stopped or restarted.";
    }
  }
  state.activity.unshift(event);
  state.activity = state.activity.slice(0, 12);
  const list = byId("activity-list");
  list.replaceChildren();
  state.activity.forEach((entry) => {
    const item = document.createElement("li");
    const time = document.createElement("span");
    time.className = "activity-time";
    time.textContent = entry.time;
    const description = document.createElement("span");
    description.className = "activity-message";
    description.textContent = entry.message;
    const inspect = document.createElement("button");
    inspect.type = "button";
    inspect.className = "text-button";
    inspect.dataset.independent = "true";
    inspect.textContent = `HTTP ${entry.status} · Inspect`;
    inspect.addEventListener("click", () => inspectRequest(entry));
    item.append(time, description, inspect);
    list.append(item);
  });
  inspectRequest(event);
}

function selectedScenario() {
  return state.scenarios.find(
    (scenario) => scenario.id === byId("guide-scenario").value,
  );
}

function showScenario() {
  const scenario = selectedScenario();
  if (!scenario) return;
  byId("guide-steps").textContent = scenario.steps;
  byId("guide-expected").textContent = scenario.expected;
  byId("guide-command").hidden = !scenario.command;
  byId("guide-command").textContent = scenario.command || "";
  codeLinks(byId("guide-code-links"), scenario.topics);
  const action = byId("prepare-scenario");
  action.hidden = !scenario.preset;
  action.textContent = [
    "bad-extension",
    "empty-csv",
    "wrong-columns",
    "numeric-missing",
  ].includes(scenario.preset)
    ? "Upload example"
    : "Prepare inputs";
}

async function prepareScenario() {
  const scenario = selectedScenario();
  if (!scenario?.preset) return;
  const uploads = {
    "bad-extension": [
      "movies.txt",
      "title,release_year,rating,genre\nMovie A,2020,8,Drama\n",
      "text/plain",
    ],
    "empty-csv": ["empty.csv", "", "text/csv"],
    "wrong-columns": [
      "wrong_columns.csv",
      "title,rating\nMovie A,8\n",
      "text/csv",
    ],
    "numeric-missing": [
      "numeric_missing.csv",
      "title,release_year,rating,genre\nMovie A,2020,8,Drama\nMovie B,unknown,8.5,Comedy\nMovie C,2022,,Drama\n",
      "text/csv",
    ],
  };
  if (uploads[scenario.preset]) {
    const [name, text, type] = uploads[scenario.preset];
    await runAction(byId("prepare-scenario"), "Uploading…", () =>
      uploadFile(new File([text], name, { type })),
    );
    return;
  }
  let nextAction;
  switch (scenario.preset) {
    case "limit-2":
      byId("row-limit").value = "2";
      nextAction = "Retrieve";
      break;
    case "invalid-limit":
      byId("row-limit").value = "0";
      nextAction = "Retrieve";
      break;
    case "search":
      byId("min-rating").value = "8.5";
      byId("search-limit").value = "2";
      byId("search-columns").value = "";
      nextAction = "Search";
      break;
    case "invalid-column":
      byId("min-rating").value = "8.5";
      byId("search-limit").value = "2";
      byId("search-columns").value = "unknown";
      nextAction = "Search";
      break;
    default:
      byId("processing-form").reset();
      byId("processing-settings").open = true;
      nextAction = "Clean collection";
      if (scenario.preset === "invalid-method")
        byId("outlier-method").value = "unsupported";
      if (scenario.preset === "negative-threshold")
        byId("outlier-threshold").value = "-1";
      if (scenario.preset === "missing-column")
        byId("extra-required-columns").value = "unknown";
      if (scenario.preset === "malformed-json") {
        byId("use-raw-body").checked = true;
        byId("raw-processing-body").value = '{"processing":';
        byId("raw-processing-body").closest("details").open = true;
      }
      updateProcessingSettings();
  }
  notify(
    `Prepared: ${scenario.title}. Click ${nextAction} to send the actual request.`,
  );
}

async function loadGuide() {
  try {
    const response = await fetch("/ui/guide", { cache: "no-store" });
    if (!response.ok)
      throw new Error(
        "Guide unavailable. Restart the server to load the updated application.",
      );
    const guide = await response.json();
    state.scenarios = guide.scenarios;
    state.topics = Object.fromEntries(
      guide.topics.map((topic) => [topic.id, topic.title]),
    );
    byId("guide-scenario").replaceChildren();
    guide.scenarios.forEach((scenario) => {
      const option = document.createElement("option");
      option.value = scenario.id;
      option.textContent = scenario.title;
      byId("guide-scenario").append(option);
    });
    showScenario();
    if (state.activity[0]) inspectRequest(state.activity[0]);
  } catch (error) {
    byId("guide-steps").textContent = error.message;
  }
}

document.addEventListener("click", (event) => {
  const link = event.target.closest("a[data-source]");
  if (link) {
    event.preventDefault();
    showSource(link.dataset.source);
  }
});
byId("close-source").addEventListener("click", () =>
  byId("source-dialog").close(),
);
byId("back-to-inputs").addEventListener("click", () =>
  byId("workflow").scrollIntoView({ block: "start" }),
);
byId("guide-scenario").addEventListener("change", showScenario);
byId("prepare-scenario").addEventListener("click", prepareScenario);
window.addEventListener("DOMContentLoaded", loadGuide);
