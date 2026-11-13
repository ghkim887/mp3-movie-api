"use strict";

const byId = (id) => document.getElementById(id);
const state = { busy: false, totalRows: 0, activity: [] };
const movieColumns = ["id", "title", "release_year", "rating", "genre"];
const columnLabels = {
  id: "ID",
  title: "Title",
  release_year: "Year",
  rating: "Rating",
  genre: "Genre",
};

// The assignment preset is the starting point and can be restored in one click.
const processingPreset = {
  validation: {
    required_columns: ["title", "release_year", "rating", "genre"],
    numeric_columns: ["release_year", "rating"],
  },
  processing: {
    remove_duplicates: true,
    missing: { enabled: true, axis: "rows" },
    outliers: {
      enabled: true,
      columns: ["rating"],
      method: "iqr",
      threshold: 1.5,
    },
  },
};

function selectedColumns(groupId) {
  return Array.from(
    byId(groupId).querySelectorAll("input:checked"),
    (input) => input.value,
  );
}

function readProcessingConfig() {
  const threshold = byId("outlier-threshold").valueAsNumber;
  return {
    validation: {
      required_columns: selectedColumns("required-columns"),
      numeric_columns: selectedColumns("numeric-columns"),
    },
    processing: {
      remove_duplicates: byId("remove-duplicates").checked,
      missing: {
        enabled: byId("missing-enabled").checked,
        axis: byId("missing-axis").value,
      },
      outliers: {
        enabled: byId("outliers-enabled").checked,
        columns: selectedColumns("outlier-columns"),
        method: byId("outlier-method").value,
        threshold: Number.isFinite(threshold)
          ? threshold
          : processingPreset.processing.outliers.threshold,
      },
    },
  };
}

function processingDescription(config) {
  const { processing } = config;
  const steps = [];
  if (processing.remove_duplicates) steps.push("duplicates");
  if (processing.missing.enabled)
    steps.push(`missing ${processing.missing.axis}`);
  if (processing.outliers.enabled && processing.outliers.columns.length) {
    const method = processing.outliers.method === "iqr" ? "IQR" : "Z-score";
    steps.push(
      `${method} ${processing.outliers.threshold} on ${processing.outliers.columns.join(", ")}`,
    );
  }
  return steps.length ? steps.join(" · ") : "No cleaning steps enabled";
}

function updateProcessingSettings() {
  const config = readProcessingConfig();
  const defaults = JSON.stringify(config) === JSON.stringify(processingPreset);
  byId("settings-summary").textContent = defaults
    ? "MP3 defaults · IQR × 1.5"
    : "Custom settings";
  byId("clean-settings-description").textContent =
    processingDescription(config);
  const threshold = config.processing.outliers.threshold;
  byId("outlier-help").textContent =
    config.processing.outliers.method === "iqr"
      ? `IQR multiplier: values outside Q1 − ${threshold} × IQR and Q3 + ${threshold} × IQR are removed.`
      : `Z-score cutoff: values more than ${threshold} standard deviations from the mean are removed.`;
  syncControls();
}

function connectionStatus(online) {
  byId("connection").className = `connection ${online ? "online" : "offline"}`;
  byId("connection-text").textContent = online
    ? "Server online"
    : "Server unavailable";
}

function syncControls() {
  document.querySelectorAll("button").forEach((button) => {
    const needsMovies = ["clean", "search-button"].includes(button.id);
    button.disabled = state.busy || (needsMovies && state.totalRows === 0);
  });
  document.querySelectorAll("input, select").forEach((input) => {
    input.disabled = state.busy;
  });
  byId("missing-options").disabled =
    state.busy || !byId("missing-enabled").checked;
  byId("outlier-options").disabled =
    state.busy || !byId("outliers-enabled").checked;
  byId("workflow").setAttribute("aria-busy", String(state.busy));
}

function notify(message, isError = false) {
  const notice = byId("notice");
  notice.className = `notice${isError ? " error" : ""}`;
  notice.setAttribute("role", isError ? "alert" : "status");
  notice.textContent = message;
  notice.hidden = !message;
}

function addActivity(message, path, method, response, duration) {
  state.activity.unshift({
    message,
    path,
    method,
    status: response.status,
    requestId: response.headers.get("X-Request-ID"),
    duration,
    time: new Date().toLocaleTimeString("en-US", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }),
  });
  state.activity = state.activity.slice(0, 6);
  const list = byId("activity-list");
  list.replaceChildren();
  state.activity.forEach((event) => {
    const item = document.createElement("li");
    const time = document.createElement("span");
    time.className = "activity-time";
    time.textContent = event.time;
    const description = document.createElement("span");
    description.className = "activity-message";
    description.textContent = event.message;
    const meta = document.createElement("span");
    meta.className = "activity-meta";
    meta.textContent = `${event.method} ${event.path} · ${event.status} · ${event.duration} ms${event.requestId ? ` · ${event.requestId}` : ""}`;
    item.append(time, description, meta);
    list.append(item);
  });
}

async function api(path, options = {}, describe = () => "Request complete") {
  const started = performance.now();
  let response;
  try {
    response = await fetch(path, { ...options, cache: "no-store" });
  } catch {
    connectionStatus(false);
    throw new Error(
      "Cannot reach the server. Start the app, then click Retrieve to reconnect.",
    );
  }
  connectionStatus(true);
  const duration = Math.round(performance.now() - started);
  const data = await response.json();
  if (!response.ok) {
    const detail =
      typeof data.detail === "string"
        ? data.detail
        : "Check your file or input and try again.";
    addActivity(
      `Request failed: ${detail}`,
      path,
      options.method || "GET",
      response,
      duration,
    );
    throw new Error(detail);
  }
  addActivity(
    describe(data, response),
    path,
    options.method || "GET",
    response,
    duration,
  );
  return { data, response, duration };
}

async function runAction(button, busyText, action) {
  if (state.busy) return;
  state.busy = true;
  const originalLabel = button ? button.innerHTML : null;
  if (button) button.textContent = busyText;
  syncControls();
  try {
    await action();
  } catch (error) {
    notify(error.message || "Something went wrong. Please try again.", true);
  } finally {
    state.busy = false;
    if (button) button.innerHTML = originalLabel;
    syncControls();
  }
}

function renderMovies(
  records,
  { search = false, minRating, limit, cache, duration } = {},
) {
  const columns = search ? ["id", "title", "rating"] : movieColumns;
  byId("total-count").textContent = state.totalRows;
  byId("table-head").replaceChildren();
  columns.forEach((column) => {
    const heading = document.createElement("th");
    heading.scope = "col";
    heading.textContent = columnLabels[column];
    byId("table-head").append(heading);
  });
  byId("movie-rows").replaceChildren();
  records.forEach((movie) => {
    const row = document.createElement("tr");
    columns.forEach((column) => {
      const cell = document.createElement("td");
      const value = movie[column];
      if (value === null || value === undefined) {
        const missing = document.createElement("span");
        missing.className = "null-value";
        missing.textContent = "Missing";
        cell.append(missing);
      } else if (column === "rating" && typeof value === "number") {
        cell.textContent = value.toFixed(1);
      } else {
        cell.textContent = String(value);
        if (column === "title") cell.className = "movie-title";
      }
      row.append(cell);
    });
    byId("movie-rows").append(row);
  });

  byId("table-container").hidden = records.length === 0;
  byId("empty-state").hidden = records.length > 0;
  byId("show-all").hidden = !search;
  byId("view-label").textContent = search
    ? "SQL search · highest ratings first"
    : "Collection · original order";
  byId("table-caption").textContent = search
    ? `${records.length} ${records.length === 1 ? "match" : "matches"} · top 2 movies rated ${minRating} or higher`
    : state.totalRows > 0
      ? `Showing ${records.length} of ${state.totalRows} movies${limit < state.totalRows ? ` · first ${limit} ${limit === 1 ? "row" : "rows"}` : ""}`
      : "Load a CSV to get started.";
  byId("accessible-caption").textContent = search
    ? `Top 2 movies with minimum rating ${minRating}`
    : "Stored movies in original row order";
  byId("empty-title").textContent = search
    ? "No movies match this rating"
    : "No movies loaded";
  byId("empty-description").textContent = search
    ? "Try a lower minimum rating, or go back to the collection."
    : "Load the sample CSV above, or choose your own movie CSV.";
  const badge = byId("source-badge");
  badge.hidden = state.totalRows === 0 && !search;
  badge.className = `source-badge${search ? " search" : cache === "MISS" ? " miss" : ""}`;
  badge.textContent = search
    ? "Not cached"
    : cache === "HIT"
      ? "Cache · HIT"
      : "Database · MISS";
  byId("request-time").textContent = `${duration} ms`;
}

async function retrieveMovies() {
  const limit = Number(byId("row-limit").value);
  const result = await api(`/movies?limit=${limit}`, {}, (data, response) => {
    const cache = response.headers.get("X-Movie-Cache");
    return `${cache === "HIT" ? "Cache HIT — skipped database reads" : "Cache MISS — read from SQLite"} · ${data.data.length} of ${data.total_rows} movies`;
  });
  state.totalRows = result.data.total_rows;
  renderMovies(result.data.data, {
    limit,
    cache: result.response.headers.get("X-Movie-Cache"),
    duration: result.duration,
  });
  return result;
}

async function refreshAfterWrite() {
  byId("row-limit").value = "100";
  try {
    await retrieveMovies();
  } catch (error) {
    // Never leave the old table looking current after a successful write.
    byId("table-container").hidden = true;
    byId("empty-state").hidden = false;
    byId("empty-title").textContent = "Changes saved";
    byId("empty-description").textContent =
      "Click Retrieve to load the updated collection.";
    byId("source-badge").hidden = true;
    byId("total-count").textContent = state.totalRows;
    byId("table-caption").textContent =
      "Saved successfully. Retrieval needs to be retried.";
    throw new Error(
      `Changes were saved, but the table could not refresh. ${error.message}`,
    );
  }
}

async function uploadFile(file) {
  const form = new FormData();
  form.append("file", file, file.name);
  const result = await api(
    "/upload",
    { method: "POST", body: form },
    (data) =>
      `Uploaded ${data.rows} movies · all previous cache entries cleared`,
  );
  state.totalRows = result.data.rows;
  byId("processing-result").hidden = true;
  await refreshAfterWrite();
  notify(
    `${file.name} loaded: ${result.data.rows} movies. Previous cache cleared. Click Retrieve to see a cache HIT.`,
  );
}

byId("load-sample").addEventListener("click", () =>
  runAction(byId("load-sample"), "Loading…", async () => {
    const response = await fetch("/sample_movies.csv", { cache: "no-store" });
    if (!response.ok)
      throw new Error(
        "The sample CSV is unavailable. Choose a CSV file instead.",
      );
    const file = new File([await response.blob()], "sample_movies.csv", {
      type: "text/csv",
    });
    await uploadFile(file);
  }),
);

byId("choose-file").addEventListener("click", () => byId("file-input").click());
byId("file-input").addEventListener("change", () => {
  const file = byId("file-input").files[0];
  byId("file-input").value = "";
  if (file)
    runAction(byId("choose-file"), "Uploading…", () => uploadFile(file));
});

byId("retrieve").addEventListener("click", () =>
  runAction(byId("retrieve"), "Retrieving…", async () => {
    const result = await retrieveMovies();
    const hit = result.response.headers.get("X-Movie-Cache") === "HIT";
    notify(
      hit
        ? "Cache HIT: this response came from the cache, so no movie retrieval or count query was needed."
        : "Cache MISS: the collection was read from SQLite and cached for 90 seconds. Retrieve the same limit again to see a HIT.",
    );
  }),
);

byId("clean").addEventListener("click", () => {
  const form = byId("processing-form");
  if (!form.checkValidity()) {
    byId("processing-settings").open = true;
    form.reportValidity();
    return;
  }
  const config = readProcessingConfig();
  runAction(byId("clean"), "Cleaning…", async () => {
    const result = await api(
      "/movies/process",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      },
      (data) =>
        `Cleaned ${data.cleaning_report.rows_before} → ${data.cleaning_report.rows_after} movies · all previous cache entries cleared`,
    );
    const report = result.data.cleaning_report;
    state.totalRows = report.rows_after;
    byId("rows-before").textContent =
      report.rows_before + result.data.validation_rows_removed;
    byId("rows-after").textContent = report.rows_after;
    const removed = report.rows_removed + result.data.validation_rows_removed;
    byId("removed-count").textContent =
      `${removed} ${removed === 1 ? "row" : "rows"} removed`;
    byId("processing-summary").textContent =
      `Validation: ${result.data.validation_rows_removed} removed · Cleaning: ${report.rows_removed} removed` +
      (report.columns_removed
        ? ` · Columns: ${report.columns_removed} removed`
        : "");
    byId("processing-result").hidden = false;
    await refreshAfterWrite();
    notify(
      "Cleaning saved. Previous cache entries cleared; the updated collection below was read from SQLite. Retrieve again to see a HIT.",
    );
  });
});

byId("processing-form").addEventListener("submit", (event) =>
  event.preventDefault(),
);
byId("processing-form").addEventListener("input", updateProcessingSettings);
byId("reset-settings").addEventListener("click", () => {
  byId("processing-form").reset();
  updateProcessingSettings();
  notify(
    "MP3 processing defaults restored. Click Clean collection to apply them.",
  );
});

byId("search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (state.totalRows === 0 || !byId("search-form").reportValidity()) return;
  runAction(byId("search-button"), "Searching…", async () => {
    const minRating = Number(byId("min-rating").value);
    const params = new URLSearchParams([
      ["columns", "title"],
      ["columns", "rating"],
      ["min_rating", String(minRating)],
      ["limit", "2"],
    ]);
    const result = await api(
      `/movies/search?${params}`,
      {},
      (data) =>
        `SQL search · ${data.length} matches rated ${minRating}+ · not cached`,
    );
    renderMovies(result.data, {
      search: true,
      minRating,
      duration: result.duration,
    });
    notify(
      "Search uses SQL to filter and sort by rating. Search responses are not cached.",
    );
  });
});

byId("show-all").addEventListener("click", () =>
  runAction(byId("show-all"), "Retrieving…", async () => {
    await retrieveMovies();
    notify("");
  }),
);

updateProcessingSettings();
runAction(null, "", async () => {
  try {
    const health = await fetch("/health", { cache: "no-store" });
    connectionStatus(health.ok);
  } catch {
    connectionStatus(false);
  }
  await retrieveMovies();
});
