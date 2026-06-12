const TODAY = "2026-06-11";
const CONFIDENCE_LABEL = { confirmed: "확정", conditional: "조건부", watch: "관찰/TBD" };
const CONFIDENCE_CLASS = { confirmed: "ok", conditional: "warn", watch: "watch" };

let state = {
  data: structuredClone(window.TIMELINE_SEED),
  primary: "all",
  secondary: "all",
  tertiary: "all",
  year: "all",
  sort: "asc",
  query: "",
  confidence: new Set(["confirmed", "conditional", "watch"])
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function formatDate(dateString) {
  const date = new Date(`${dateString}T00:00:00Z`);
  return new Intl.DateTimeFormat("ko-KR", { year: "numeric", month: "long", day: "numeric", weekday: "short", timeZone: "UTC" }).format(date);
}

function getYear(event) {
  return event.date.slice(0, 4);
}

function categoryLabel(categoryId) {
  return state.data.taxonomy.find((item) => item.id === categoryId)?.label ?? categoryId;
}

function renderPrimaryTabs() {
  const container = $("#primaryTabs");
  const buttons = [{ id: "all", label: "전체" }, ...state.data.taxonomy.map(({ id, label }) => ({ id, label }))];
  container.innerHTML = buttons.map((button) => `
    <button type="button" class="topic-tab ${state.primary === button.id ? "active" : ""}" data-id="${button.id}">${button.label}</button>
  `).join("");
  $$(".topic-tab").forEach((button) => button.addEventListener("click", () => {
    state.primary = button.dataset.id;
    state.secondary = "all";
    state.tertiary = "all";
    render();
  }));
}

function renderSelects() {
  const secondary = $("#secondarySelect");
  const availableTopics = state.primary === "all"
    ? [...new Set(state.data.taxonomy.flatMap((item) => item.children))]
    : state.data.taxonomy.find((item) => item.id === state.primary)?.children ?? [];
  secondary.innerHTML = `<option value="all">전체</option>${availableTopics.map((topic) => `<option value="${topic}">${topic}</option>`).join("")}`;
  secondary.value = state.secondary;

  const markets = [...new Set(state.data.events
    .filter((event) => state.secondary === "all" || event.topic === state.secondary)
    .map((event) => event.market))].sort();
  const tertiary = $("#tertiarySelect");
  tertiary.innerHTML = `<option value="all">전체 시장</option>${markets.map((market) => `<option value="${market}">${market}</option>`).join("")}`;
  tertiary.value = state.tertiary;
}

function renderYears() {
  const years = [...new Set(state.data.events.map(getYear))].sort();
  $("#yearSelect").innerHTML = `<option value="all">전체</option>${years.map((year) => `<option value="${year}">${year}</option>`).join("")}`;
  $("#yearSelect").value = state.year;
}

function filteredEvents() {
  const q = state.query.trim().toLowerCase();
  return state.data.events.filter((event) => {
    const haystack = [event.title, event.topic, event.market, event.impact, event.description, categoryLabel(event.category)].join(" ").toLowerCase();
    return (state.primary === "all" || event.category === state.primary)
      && (state.secondary === "all" || event.topic === state.secondary)
      && (state.tertiary === "all" || event.market === state.tertiary)
      && (state.year === "all" || getYear(event) === state.year)
      && state.confidence.has(event.confidence)
      && (!q || haystack.includes(q));
  }).sort((a, b) => state.sort === "asc" ? a.date.localeCompare(b.date) : b.date.localeCompare(a.date));
}

function renderSummary(events) {
  $("#totalCount").textContent = events.length;
  $("#upcomingCount").textContent = events.filter((event) => event.date >= TODAY).length;
  $("#confirmedCount").textContent = events.filter((event) => event.confidence === "confirmed").length;
  $("#watchCount").textContent = events.filter((event) => event.confidence === "watch").length;
  $("#lastUpdated").textContent = `데이터 기준일: ${state.data.generatedAt}`;
  const titleParts = [state.primary === "all" ? "전체 이벤트" : categoryLabel(state.primary)];
  if (state.secondary !== "all") titleParts.push(state.secondary);
  if (state.tertiary !== "all") titleParts.push(state.tertiary);
  $("#timelineTitle").textContent = titleParts.join(" › ");
}

function renderTimeline(events) {
  const timeline = $("#timeline");
  $("#emptyState").hidden = events.length > 0;
  timeline.innerHTML = events.map((event) => {
    const timing = event.date < TODAY ? "past" : event.date === TODAY ? "today" : "future";
    return `
      <li class="timeline-item ${timing}">
        <button type="button" class="event-card" data-id="${event.id}">
          <span class="date-block"><strong>${formatDate(event.date)}</strong><small>${event.market} · ${categoryLabel(event.category)}</small></span>
          <span class="event-main">
            <span class="badges"><span class="badge ${CONFIDENCE_CLASS[event.confidence]}">${CONFIDENCE_LABEL[event.confidence]}</span><span class="badge muted">${event.topic}</span></span>
            <strong>${event.title}</strong>
            <span>${event.impact}</span>
          </span>
        </button>
      </li>
    `;
  }).join("");
  $$(".event-card").forEach((card) => card.addEventListener("click", () => openDetail(card.dataset.id)));
}

function openDetail(id) {
  const event = state.data.events.find((item) => item.id === id);
  if (!event) return;
  const sourceLinks = event.sources.map((key) => {
    const source = state.data.sources[key];
    return `<li><a href="${source.url}" target="_blank" rel="noreferrer">${source.label}</a></li>`;
  }).join("");
  $("#detailContent").innerHTML = `
    <p class="eyebrow">상세 화면</p>
    <h2>${event.title}</h2>
    <div class="detail-meta">
      <span>${formatDate(event.date)}</span>
      <span>${event.market}</span>
      <span>${categoryLabel(event.category)} › ${event.topic}</span>
      <span class="badge ${CONFIDENCE_CLASS[event.confidence]}">${CONFIDENCE_LABEL[event.confidence]}</span>
    </div>
    <h3>투자자 관점 체크포인트</h3>
    <p>${event.impact}</p>
    <h3>설명</h3>
    <p>${event.description}</p>
    <h3>출처</h3>
    <ul class="source-list">${sourceLinks}</ul>
    <p class="disclaimer">이 로컬 페이지는 일정 정리를 돕는 도구이며 투자 권유가 아닙니다. IPO·공모 조건은 최종 투자설명서와 거래소 공시를 반드시 확인하세요.</p>
  `;
  $("#detailDialog").showModal();
}

function bindEvents() {
  $("#secondarySelect").addEventListener("change", (event) => { state.secondary = event.target.value; state.tertiary = "all"; render(); });
  $("#tertiarySelect").addEventListener("change", (event) => { state.tertiary = event.target.value; render(); });
  $("#yearSelect").addEventListener("change", (event) => { state.year = event.target.value; render(); });
  $("#sortSelect").addEventListener("change", (event) => { state.sort = event.target.value; render(); });
  $("#searchInput").addEventListener("input", (event) => { state.query = event.target.value; render(); });
  $$(".confidenceFilter").forEach((input) => input.addEventListener("change", () => {
    state.confidence = new Set($$(".confidenceFilter").filter((box) => box.checked).map((box) => box.value));
    render();
  }));
  $("#closeDialog").addEventListener("click", () => $("#detailDialog").close());
  $("#downloadJson").addEventListener("click", downloadJson);
  $("#importJson").addEventListener("change", importJson);
}

function downloadJson() {
  const blob = new Blob([JSON.stringify(state.data, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `economic-timeline-${state.data.generatedAt}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function importJson(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const parsed = JSON.parse(reader.result);
      if (!Array.isArray(parsed.events) || !Array.isArray(parsed.taxonomy) || !parsed.sources) {
        throw new Error("Invalid timeline JSON");
      }
      state.data = parsed;
      state.primary = "all";
      state.secondary = "all";
      state.tertiary = "all";
      state.year = "all";
      render();
    } catch (error) {
      alert(`JSON을 불러오지 못했습니다: ${error.message}`);
    }
  };
  reader.readAsText(file);
}

function render() {
  renderPrimaryTabs();
  renderSelects();
  renderYears();
  const events = filteredEvents();
  renderSummary(events);
  renderTimeline(events);
}

bindEvents();
render();
