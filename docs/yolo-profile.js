const STACK_COLORS = ["#0f5c4c", "#b85c38", "#1f6f8b", "#6d5a45", "#8a8f7a", "#3e4c5e", "#c4a574"];
const PIE_COLORS = ["#0f5c4c", "#b85c38", "#1f6f8b", "#6d5a45", "#c4a574", "#3e4c5e", "#8a8f7a", "#7a3e4a", "#2f6b4f", "#4c5d73", "#d38b6a", "#3d7a6a", "#8c6b3e", "#5b6e8a", "#6e8b4e"];

const $ = (id) => document.getElementById(id);

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function count(value) {
  if (value == null || value === "") return "Not published";
  return new Intl.NumberFormat("en-US").format(value);
}

function money(value) {
  if (value == null || Number.isNaN(Number(value))) return "Not published";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

function withMoe(percent, moe) {
  if (percent == null) return "Not published";
  if (moe == null || moe === "") return `${percent}%`;
  return `${percent}% ± ${Number(moe).toFixed(1)}`;
}

function percentOf(label) {
  const match = String(label ?? "").match(/([\d.]+)\s*%/);
  return match ? Number(match[1]) : null;
}

function bars(items, valueOf, labelOf, noteOf) {
  const values = items.map(valueOf).map((value) => Number(value) || 0);
  const max = Math.max(...values, 1);
  return `<div class="bar-list">${items
    .map((item, index) => {
      const value = values[index];
      const width = Math.max(2, Math.round((value / max) * 100));
      const note = noteOf ? noteOf(item) : count(value);
      return `<div class="bar-row">
        <span class="bar-label">${esc(labelOf(item))}</span>
        <span class="bar-track"><span class="bar-fill" style="width:${width}%"></span></span>
        <span class="bar-value">${esc(note)}</span>
      </div>`;
    })
    .join("")}</div>`;
}

function stack(parts) {
  const total = parts.reduce((sum, part) => sum + part.value, 0) || 1;
  const legend = parts
    .map(
      (part, index) =>
        `<li><i style="background:${STACK_COLORS[index % STACK_COLORS.length]}"></i>${esc(part.label)} ${esc(part.display)}</li>`
    )
    .join("");
  const pieces = parts
    .map((part, index) => {
      const width = (part.value / total) * 100;
      return `<span style="width:${width}%;background:${STACK_COLORS[index % STACK_COLORS.length]}" title="${esc(part.label)} ${esc(part.display)}"></span>`;
    })
    .join("");
  return `<div class="stack" aria-hidden="true">${pieces}</div><ul class="legend">${legend}</ul>`;
}

function mountMenu(container, tabs, onPick) {
  container.innerHTML = tabs
    .map(
      (tab, index) =>
        `<button type="button" role="tab" data-tab="${esc(tab.id)}" aria-pressed="${index === 0 ? "true" : "false"}">${esc(tab.label)}</button>`
    )
    .join("");
  container.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-tab]");
    if (!button) return;
    container.querySelectorAll("button").forEach((item) => item.setAttribute("aria-pressed", "false"));
    button.setAttribute("aria-pressed", "true");
    onPick(button.dataset.tab);
  });
  onPick(tabs[0].id);
}

function fillSelect(select, values, allLabel) {
  const unique = [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
  select.innerHTML = `<option value="">${esc(allLabel)}</option>${unique
    .map((value) => `<option value="${esc(value)}">${esc(value)}</option>`)
    .join("")}`;
}

function renderSnapshot(profile) {
  const views = profile.views;
  const income = profile.income.summaries.find((row) => row.label.startsWith("Median income"));
  const poverty = profile.poverty[0]?.rows?.[0];
  const household = income?.values?.Households?.value;
  const cards = [
    ["Population", count(views.population.estimate)],
    ["Median age", views.median_age.estimate ?? "Not published"],
    ["Median household income", money(household)],
    ["Below poverty", poverty ? withMoe(poverty.percent, poverty.percent_moe) : "Not published"],
    ["Major employers", count(profile.employers.length)],
    ["Union locals on the map", count(profile.unions.markers.length)],
  ];
  $("stat-grid").innerHTML = cards
    .map(([label, value]) => `<article class="stat"><span>${esc(label)}</span><strong>${esc(value)}</strong></article>`)
    .join("");

  const under18 = percentOf(views.under_18.percent) || 0;
  const over65 = percentOf(views.over_65.percent) || 0;
  const working = Math.max(0, Math.round((100 - under18 - over65) * 10) / 10);
  const sex = views.sex.map((row) => ({
    label: row.label,
    value: percentOf(row.percent) || 0,
    display: row.percent,
  }));
  const race = views.race.map((row) => ({
    label: row.label,
    value: percentOf(row.percent) || 0,
    display: row.percent,
  }));
  $("snapshot-charts").innerHTML = `
    <div class="panel-grid" style="margin-top:0.75rem">
      <article class="sheet">
        <p class="eyebrow">Age</p>
        <h3>Share of the population</h3>
        ${stack([
          { label: "Under 18", value: under18, display: views.under_18.percent },
          { label: "18 to 64", value: working, display: `${working}%` },
          { label: "65 and over", value: over65, display: views.over_65.percent },
        ])}
      </article>
      <article class="sheet">
        <p class="eyebrow">Sex</p>
        <h3>Residents</h3>
        ${stack(sex)}
      </article>
    </div>
    <article class="sheet">
      <p class="eyebrow">Race alone, plus two or more races</p>
      <h3>How residents identified</h3>
      ${stack(race)}
      <p class="hint">Hispanic or Latino origin is tracked separately. It is in the People menu.</p>
    </article>`;
}

function chartSwitch(kind, label) {
  return `<div class="menu chart-switch" role="group" aria-label="${esc(label)}">
    <button type="button" data-chart="bars" aria-pressed="${kind === "bars" ? "true" : "false"}">Bars</button>
    <button type="button" data-chart="pie" aria-pressed="${kind === "pie" ? "true" : "false"}">Pie</button>
  </div>`;
}

function bindChartSwitch(root, onPick) {
  root.querySelector(".chart-switch")?.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-chart]");
    if (!button) return;
    onPick(button.dataset.chart);
  });
}

function chartFor(kind, items, valueOf, labelOf, noteOf) {
  return kind === "pie"
    ? pieChart(items, valueOf, labelOf, noteOf)
    : bars(items, valueOf, labelOf, noteOf);
}

function decadeAge(rows) {
  const byLabel = new Map(rows.map((row) => [row.label, row]));
  const bands = [
    ["Under 10 years", ["Under 5 years", "5 to 9 years"]],
    ["10 to 19 years", ["10 to 14 years", "15 to 19 years"]],
    ["20 to 24 years", ["20 to 24 years"]],
    ["25 to 34 years", ["25 to 34 years"]],
    ["35 to 44 years", ["35 to 44 years"]],
    ["45 to 54 years", ["45 to 54 years"]],
    ["55 to 64 years", ["55 to 59 years", "60 to 64 years"]],
    ["65 to 74 years", ["65 to 74 years"]],
    ["75 to 84 years", ["75 to 84 years"]],
    ["85 years and over", ["85 years and over"]],
  ];
  return bands
    .map(([label, parts]) => ({
      label,
      estimate: parts.reduce((sum, name) => sum + (byLabel.get(name)?.estimate || 0), 0),
    }))
    .filter((row) => row.estimate > 0);
}

function renderPeople(profile) {
  const views = profile.views;
  const panel = $("people-panel");
  const tabs = [
    { id: "age", label: "Age" },
    { id: "race", label: "Race" },
    { id: "hispanic", label: "Hispanic origin" },
  ];
  let raceFocus = views.race[0]?.label || "";
  let peopleChart = "bars";
  const peopleNote = (row) =>
    peopleChart === "pie" ? count(row.estimate) : `${row.percent} · ${count(row.estimate)}`;

  function draw(tab) {
    const switcher = chartSwitch(peopleChart, "People chart");
    if (tab === "age") {
      panel.innerHTML = `
        ${switcher}
        <p class="eyebrow">Age bands</p>
        ${chartFor(
          peopleChart,
          peopleChart === "pie" ? decadeAge(views.age) : views.age,
          (row) => row.estimate || 0,
          (row) => row.label,
          peopleNote
        )}
        ${peopleChart === "pie" ? `<p class="hint">Ten-year bands where the spreadsheet publishes them. 20 to 24 years stays a 5-year band because the next published band is 25 to 34 years.</p>` : ""}`;
      bindChartSwitch(panel, (kind) => {
        peopleChart = kind;
        draw(tab);
      });
      return;
    }
    if (tab === "race") {
      const group = views.race.find((item) => item.label === raceFocus) || views.race[0];
      const choices = views.race
        .map(
          (item) =>
            `<button type="button" data-race="${esc(item.label)}" aria-pressed="${item.label === group.label ? "true" : "false"}">${esc(item.label)}</button>`
        )
        .join("");
      const detail = group.children.length
        ? chartFor(
            peopleChart,
            group.children,
            (row) => row.estimate || 0,
            (row) => row.label,
            (row) => (peopleChart === "pie" ? count(row.estimate) : row.percent)
          )
        : `<p class="hint">No finer breakdown in the spreadsheet.</p>`;
      const groupPie =
        peopleChart === "pie"
          ? `<p class="eyebrow">Race groups</p>
        ${pieChart(views.race, (row) => row.estimate || 0, (row) => row.label, (row) => count(row.estimate))}`
          : "";
      panel.innerHTML = `
        ${switcher}
        ${groupPie}
        <p class="eyebrow">${peopleChart === "pie" ? "Within a race group" : "Race group"}</p>
        <div class="menu" id="race-menu">${choices}</div>
        <p><strong>${esc(group.label)}</strong> ${esc(group.percent)} · ${count(group.estimate)}</p>
        ${detail}`;
      bindChartSwitch(panel, (kind) => {
        peopleChart = kind;
        draw(tab);
      });
      panel.querySelector("#race-menu").addEventListener("click", (event) => {
        const button = event.target.closest("button[data-race]");
        if (!button) return;
        raceFocus = button.dataset.race;
        draw("race");
      });
      return;
    }
    const originParts = views.hispanic_origin.slice(1);
    const raceParts = views.hispanic_race.filter(
      (row) => row.percent && row.percent !== "(X)" && row.label !== "Not Hispanic or Latino" && !row.label.startsWith("Two races")
    );
    panel.innerHTML = `
      ${switcher}
      <p class="eyebrow">Hispanic or Latino origin</p>
      ${chartFor(
        peopleChart,
        peopleChart === "pie" ? originParts : views.hispanic_origin,
        (row) => row.estimate || 0,
        (row) => row.label,
        peopleNote
      )}
      <p class="eyebrow" style="margin-top:1rem">Not Hispanic or Latino, by race</p>
      ${chartFor(
        peopleChart,
        peopleChart === "pie" ? raceParts : views.hispanic_race,
        (row) => (peopleChart === "pie" ? row.estimate || 0 : percentOf(row.percent) || 0),
        (row) => row.label,
        (row) => (peopleChart === "pie" ? count(row.estimate) : row.percent)
      )}`;
    bindChartSwitch(panel, (kind) => {
      peopleChart = kind;
      draw(tab);
    });
  }

  mountMenu($("people-menu"), tabs, draw);
}

const HOUSEHOLD_HELP = {
  Households:
    "Everyone living in one occupied home, including a person who lives alone. A household can be a family plus any unrelated roommates. Each occupied home counts as one household.",
  Families:
    "A householder and at least one other person related by birth, marriage, or adoption. A person living alone, or a home of only unrelated roommates, is not a family.",
  "Married-couple families":
    "A family in which the householder and their spouse live in the same home. Married-couple families are a subset of families.",
  "Nonfamily households":
    "A householder living alone, or living only with people who are not related to them. Households equal families plus nonfamily households.",
};

function termLabel(group, focusable = true) {
  const help = HOUSEHOLD_HELP[group];
  if (!help) return esc(group);
  const tab = focusable ? " tabindex=\"0\"" : "";
  return `<span class="term"${tab}>${esc(group)}<span class="term-tip" role="tooltip">${esc(help)}</span></span>`;
}

function renderIncome(profile) {
  const panel = $("income-panel");
  const groups = profile.income.groups;
  const medians = profile.income.summaries
    .map((row) => {
      const bits = groups
        .map(
          (group) =>
            `<article class="stat"><span>${termLabel(group)}</span><strong>${money(row.values[group]?.value)}</strong></article>`
        )
        .join("");
      return `<p class="eyebrow">${esc(row.label)}</p><div class="stat-grid">${bits}</div>`;
    })
    .join("");

  let incomeChart = "bars";
  let incomeGroup = groups[0];
  let earnField = "total_label";

  function payBands() {
    if (profile.earnings.bands?.length) return profile.earnings.bands;
    return (profile.earnings.headlines || []).filter((row) => String(row.total_label || "").includes("%"));
  }

  function draw(tab) {
    if (tab === "households") {
      const bands = profile.income.distribution;
      const menu = groups
        .map(
          (group) =>
            `<button type="button" data-group="${esc(group)}" aria-pressed="${group === incomeGroup ? "true" : "false"}">${termLabel(group, false)}</button>`
        )
        .join("");
      panel.innerHTML = `
        ${medians}
        <p class="eyebrow" style="margin-top:1rem">Income distribution</p>
        ${chartSwitch(incomeChart, "Income distribution chart")}
        <div class="menu" id="income-groups">${menu}</div>
        <div id="income-bars"></div>`;
      const drawGroup = (group) => {
        incomeGroup = group;
        panel.querySelector("#income-bars").innerHTML = chartFor(
          incomeChart,
          bands,
          (row) => row.values[group]?.value || 0,
          (row) => row.label,
          incomeChart === "pie" ? null : (row) => row.values[group]?.raw || ""
        );
      };
      bindChartSwitch(panel, (kind) => {
        incomeChart = kind;
        draw(tab);
      });
      panel.querySelector("#income-groups").addEventListener("click", (event) => {
        const button = event.target.closest("button[data-group]");
        if (!button) return;
        panel.querySelectorAll("#income-groups button").forEach((item) => item.setAttribute("aria-pressed", "false"));
        button.setAttribute("aria-pressed", "true");
        drawGroup(button.dataset.group);
      });
      drawGroup(incomeGroup);
      return;
    }
    if (tab === "earnings") {
      const fullTime = payBands();
      const countField = { total_label: "total", male_label: "male", female_label: "female" };
      panel.innerHTML = `
        ${chartSwitch(incomeChart, "Pay band chart")}
        <p class="eyebrow">Full-time, year-round workers</p>
        <div class="menu" id="earn-menu">
          <button type="button" data-field="total_label" aria-pressed="${earnField === "total_label" ? "true" : "false"}">All</button>
          <button type="button" data-field="male_label" aria-pressed="${earnField === "male_label" ? "true" : "false"}">Men</button>
          <button type="button" data-field="female_label" aria-pressed="${earnField === "female_label" ? "true" : "false"}">Women</button>
        </div>
        <div id="earn-bars"></div>`;
      const drawField = (field) => {
        earnField = field;
        const valueOf = (row) =>
          incomeChart === "pie" ? row[countField[field]] || 0 : percentOf(row[field]) || 0;
        const noteOf = (row) => (incomeChart === "pie" ? count(row[countField[field]]) : row[field]);
        panel.querySelector("#earn-bars").innerHTML = chartFor(incomeChart, fullTime, valueOf, (row) => row.label, noteOf);
      };
      bindChartSwitch(panel, (kind) => {
        incomeChart = kind;
        draw(tab);
      });
      panel.querySelector("#earn-menu").addEventListener("click", (event) => {
        const button = event.target.closest("button[data-field]");
        if (!button) return;
        panel.querySelectorAll("#earn-menu button").forEach((item) => item.setAttribute("aria-pressed", "false"));
        button.setAttribute("aria-pressed", "true");
        drawField(button.dataset.field);
      });
      drawField(earnField);
      return;
    }
    const rows = profile.earnings.education;
    panel.innerHTML = `
      <p class="eyebrow">Median earnings by education, population 25 and over</p>
      ${bars(rows, (row) => row.total || 0, (row) => row.label, (row) => `${money(row.total)} all · ${money(row.male)} men · ${money(row.female)} women`)}`;
  }

  mountMenu($("income-menu"), [
    { id: "households", label: "Households" },
    { id: "earnings", label: "Pay bands" },
    { id: "education", label: "Education" },
  ], draw);
}

function occupationRows(nodes, depth, whole) {
  const scale = whole || Math.max(...nodes.map((node) => node.total || 0), 1);
  return nodes
    .map((node) => {
      const width = Math.round((((node.total || 0) / scale) * 100) * 10) / 10;
      const nested = node.children?.length ? occupationRows(node.children, depth + 1, scale) : "";
      const fill = depth > 1 ? "bar-fill sub-deep" : depth > 0 ? "bar-fill sub" : "bar-fill";
      return `<div class="bar-row">
        <span class="bar-label" style="padding-left:${depth * 0.85}rem">${esc(node.label)}</span>
        <span class="bar-track"><span class="${fill}" style="width:${width}%"></span></span>
        <span class="bar-value">${count(node.total)}</span>
      </div>${nested}`;
    })
    .join("");
}

function pieChart(items, valueOf, labelOf, noteOf) {
  const rows = items
    .map((item, index) => ({
      label: labelOf(item),
      note: noteOf ? String(noteOf(item)) : "",
      value: Number(valueOf(item)) || 0,
      index,
    }))
    .filter((row) => row.value > 0);
  const total = rows.reduce((sum, row) => sum + row.value, 0) || 1;
  const cx = 100;
  const cy = 100;
  const radius = 78;
  let angle = -Math.PI / 2;
  const paths = rows.map((row, index) => {
    const share = row.value / total;
    const start = angle;
    const end = index === rows.length - 1 ? Math.PI * 1.5 : angle + share * Math.PI * 2;
    angle = end;
    const color = PIE_COLORS[row.index % PIE_COLORS.length];
    const title = `${esc(row.label)} ${esc(row.note)}`.trim();
    if (share >= 0.999) {
      return `<circle cx="${cx}" cy="${cy}" r="${radius}" fill="${color}"><title>${title}</title></circle>`;
    }
    const x1 = (cx + radius * Math.cos(start)).toFixed(2);
    const y1 = (cy + radius * Math.sin(start)).toFixed(2);
    const x2 = (cx + radius * Math.cos(end)).toFixed(2);
    const y2 = (cy + radius * Math.sin(end)).toFixed(2);
    const large = end - start > Math.PI ? 1 : 0;
    return `<path d="M ${cx} ${cy} L ${x1} ${y1} A ${radius} ${radius} 0 ${large} 1 ${x2} ${y2} Z" fill="${color}"><title>${title}</title></path>`;
  });
  const legend = rows
    .map((row) => {
      const color = PIE_COLORS[row.index % PIE_COLORS.length];
      const pct = Math.round((row.value / total) * 1000) / 10;
      const note = row.note ? ` · ${esc(row.note)}` : "";
      return `<li><i style="background:${color}"></i>${esc(row.label)}${note} · ${pct}%</li>`;
    })
    .join("");
  return `<div class="pie-wrap"><svg viewBox="0 0 200 200" role="img" aria-label="Pie chart">${paths.join("")}</svg><ul class="legend">${legend}</ul></div>`;
}

function renderWork(profile) {
  const panel = $("work-panel");
  const occupations = profile.occupations;
  let groupLabel = occupations.groups[0]?.label || "";
  let occChart = "bars";
  let povertyTitle = profile.poverty.find((section) => section.title === "Age")?.title || profile.poverty[0].title;

  function draw(tab) {
    if (tab === "occupations") {
      const employed = occupations.total?.total || 1;
      const menu = occupations.groups
        .map(
          (group) =>
            `<button type="button" data-group="${esc(group.label)}" aria-pressed="${group.label === groupLabel ? "true" : "false"}">${esc(group.label.replace(" occupations", ""))}</button>`
        )
        .join("");
      const group = occupations.groups.find((item) => item.label === groupLabel) || occupations.groups[0];
      const share = Math.round(((group.total || 0) / employed) * 1000) / 10;
      const groupNote = (row) => `${count(row.total)} · ${Math.round(((row.total || 0) / employed) * 1000) / 10}%`;
      const groupLabelText = (row) => row.label.replace(" occupations", "");
      const summary =
        occChart === "pie"
          ? pieChart(occupations.groups, (row) => row.total || 0, groupLabelText, (row) => count(row.total))
          : bars(occupations.groups, (row) => row.total || 0, groupLabelText, groupNote);
      const detail =
        occChart === "pie"
          ? pieChart(group.children, (row) => row.total || 0, (row) => row.label, (row) => count(row.total))
          : `<div class="bar-list">${occupationRows(group.children, 0)}</div>`;
      panel.innerHTML = `
        <div class="menu chart-switch" role="group" aria-label="Occupation chart">
          <button type="button" data-chart="bars" aria-pressed="${occChart === "bars" ? "true" : "false"}">Bars</button>
          <button type="button" data-chart="pie" aria-pressed="${occChart === "pie" ? "true" : "false"}">Pie</button>
        </div>
        <p class="eyebrow">${count(employed)} civilian employed residents</p>
        ${summary}
        <div class="menu" id="occ-menu">${menu}</div>
        <p><strong>${esc(group.label)}</strong> · ${esc(share)}% of employed residents</p>
        <div class="split" aria-hidden="true">
          <span style="width:${esc(group.male_percent)}"></span>
          <span style="width:${esc(group.female_percent)}"></span>
        </div>
        <p class="hint">${esc(group.male_percent)} men · ${esc(group.female_percent)} women</p>
        ${detail}`;
      panel.querySelector(".chart-switch").addEventListener("click", (event) => {
        const button = event.target.closest("button[data-chart]");
        if (!button) return;
        occChart = button.dataset.chart;
        draw("occupations");
      });
      panel.querySelector("#occ-menu").addEventListener("click", (event) => {
        const button = event.target.closest("button[data-group]");
        if (!button) return;
        groupLabel = button.dataset.group;
        draw("occupations");
      });
      return;
    }
    const menu = profile.poverty
      .filter((section) => section.rows.some((row) => row.percent != null))
      .map(
        (section) =>
          `<button type="button" data-section="${esc(section.title)}" aria-pressed="${section.title === povertyTitle ? "true" : "false"}">${esc(section.title)}</button>`
      )
      .join("");
    const section = profile.poverty.find((item) => item.title === povertyTitle) || profile.poverty[0];
    const rows = section.rows.filter((row) => row.percent != null);
    panel.innerHTML = `
      <p class="eyebrow">Percent below the poverty level</p>
      <div class="menu" id="pov-menu">${menu}</div>
      ${bars(rows, (row) => row.percent || 0, (row) => row.label, (row) => withMoe(row.percent, row.percent_moe))}`;
    panel.querySelector("#pov-menu").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-section]");
      if (!button) return;
      povertyTitle = button.dataset.section;
      draw("poverty");
    });
  }

  mountMenu($("work-menu"), [
    { id: "occupations", label: "Occupations" },
    { id: "poverty", label: "Poverty" },
  ], draw);
}

function popupHtml(item) {
  if (item.kind === "employer") {
    return `<strong>${esc(item.name)}</strong><br>${esc(item.industry)}<br>${esc(item.city)}<br><span>${esc(item.note || "")}</span>`;
  }
  const units = (item.units || [])
    .map((unit) => `${esc(unit.unit || unit.employer)}${unit.workers ? ` (${count(unit.workers)})` : ""}`)
    .join("<br>");
  const counted = item.workers_counted ? `<br>${count(item.workers_counted)} workers in counted units` : "";
  return `<strong>${esc(item.name)}</strong><br>${esc(item.place_name)} · ${esc(item.city)}${counted}<br>${units}<br><span>${esc(item.note)}</span>`;
}

function loadMapConfig() {
  return new Promise((resolve) => {
    const script = document.createElement("script");
    script.src = "map-config.js";
    script.onload = () => resolve();
    script.onerror = () => resolve();
    document.head.appendChild(script);
  });
}

function mapTiles() {
  const key = String(window.MAP_TILE_KEY || "");
  const template = window.MAP_TILE_URL
    || (key ? "https://api.maptiler.com/maps/dataviz/{z}/{x}/{y}.png?key={key}" : "");
  if (key && template) {
    return {
      url: template.replaceAll("{key}", encodeURIComponent(key)),
      attribution: window.MAP_TILE_ATTRIBUTION
        || '&copy; <a href="https://www.maptiler.com/copyright/">MapTiler</a> &copy; OpenStreetMap',
    };
  }
  return {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    labels: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
    attribution: "Tiles &copy; Esri, DeLorme, NAVTEQ",
    maxZoom: 16,
  };
}

function renderMap(profile) {
  const places = [
    ...profile.employers.map((item) => ({ ...item, kind: "employer" })),
    ...profile.unions.markers.map((item) => ({ ...item, kind: "union" })),
  ].filter((item) => item.lat != null && item.lng != null);

  const map = L.map("county-map", { scrollWheelZoom: false });
  const tiles = mapTiles();
  const tileOptions = {
    attribution: tiles.attribution,
    maxZoom: tiles.maxZoom || 19,
  };
  if (tiles.subdomains) tileOptions.subdomains = tiles.subdomains;
  L.tileLayer(tiles.url, tileOptions).addTo(map);
  if (tiles.labels) L.tileLayer(tiles.labels, { maxZoom: tiles.maxZoom || 19, pane: "overlayPane" }).addTo(map);

  const employers = L.markerClusterGroup({ showCoverageOnHover: false });
  const unions = L.markerClusterGroup({ showCoverageOnHover: false });
  const markers = places.map((item) => {
    const color = item.kind === "union" ? "#b85c38" : "#0f5c4c";
    const marker = L.circleMarker([item.lat, item.lng], {
      radius: item.kind === "union" ? 7 : 8,
      color,
      weight: 2,
      fillColor: color,
      fillOpacity: 0.88,
    });
    marker.bindPopup(popupHtml(item), { maxWidth: 320 });
    marker.item = item;
    return marker;
  });

  let kind = "all";
  let city = "";
  let query = "";

  function visibleMarkers() {
    return markers.filter((marker) => {
      const item = marker.item;
      if (kind !== "all" && item.kind !== kind) return false;
      if (city && item.city !== city) return false;
      if (!query) return true;
      const haystack = [item.name, item.city, item.industry, item.place_name, item.note]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    });
  }

  function paint() {
    employers.clearLayers();
    unions.clearLayers();
    const shown = visibleMarkers();
    shown.forEach((marker) => {
      (marker.item.kind === "union" ? unions : employers).addLayer(marker);
    });
    $("map-list").innerHTML = shown
      .map((marker, index) => {
        const item = marker.item;
        const detail = item.kind === "union" ? item.place_name : item.industry;
        return `<li><button type="button" data-index="${index}">
          <strong>${esc(item.name)}</strong>
          <small>${esc(item.city)} · ${esc(detail || "")}</small>
        </button></li>`;
      })
      .join("");
    $("map-list").querySelectorAll("button").forEach((button) => {
      button.addEventListener("click", () => {
        const marker = shown[Number(button.dataset.index)];
        $("map-list").querySelectorAll("button").forEach((item) => item.removeAttribute("aria-current"));
        button.setAttribute("aria-current", "true");
        map.flyTo(marker.getLatLng(), 14);
        marker.openPopup();
      });
    });
  }

  fetch("data/yolo-county.geojson")
    .then((response) => response.json())
    .then((geo) => {
      const layer = L.geoJSON(geo, {
        style: { color: "#0f5c4c", weight: 2, fillColor: "#0f5c4c", fillOpacity: 0.06 },
      }).addTo(map);
      map.fitBounds(layer.getBounds(), { padding: [16, 16] });
    })
    .catch(() => {
      map.setView([38.68, -121.9], 10);
    });

  employers.addTo(map);
  unions.addTo(map);
  fillSelect($("map-city"), places.map((item) => item.city), "All cities");
  mountMenu($("map-kind"), [
    { id: "all", label: "All" },
    { id: "employer", label: "Employers" },
    { id: "union", label: "Unions" },
  ], (next) => {
    kind = next;
    paint();
  });
  $("map-city").addEventListener("change", () => {
    city = $("map-city").value;
    paint();
  });
  $("map-search").addEventListener("input", () => {
    query = $("map-search").value.trim().toLowerCase();
    paint();
  });
  paint();
  setTimeout(() => map.invalidateSize(), 200);
}

function linkTarget(value) {
  const text = String(value || "");
  const match = text.match(/https?:\/\/\S+/);
  return match ? match[0] : "";
}

function renderUnions(profile) {
  const rows = profile.unions.rows.filter((row) => !String(row.union).toLowerCase().startsWith("unknown"));
  const counted = rows.reduce((sum, row) => sum + (row.workers || 0), 0);
  const withCounts = rows.filter((row) => row.workers).length;
  $("union-note").textContent = profile.unions.note;
  $("union-stats").innerHTML = [
    ["Relationships", count(rows.length)],
    ["Locals on the map", count(profile.unions.markers.length)],
    ["Units with a count", count(withCounts)],
    ["Workers in those units", count(counted)],
  ]
    .map(([label, value]) => `<article class="stat"><span>${esc(label)}</span><strong>${esc(value)}</strong></article>`)
    .join("");

  fillSelect($("union-city"), rows.map((row) => row.city), "All cities");
  fillSelect($("union-sector"), rows.map((row) => row.sector), "All sectors");
  fillSelect($("union-status"), rows.map((row) => row.status), "All statuses");

  function groupRows(matched) {
    const groups = [];
    const index = new Map();
    for (const row of matched) {
      if (!index.has(row.union)) {
        index.set(row.union, groups.length);
        groups.push({ union: row.union, units: [] });
      }
      groups[index.get(row.union)].units.push(row);
    }
    return groups;
  }

  function workplaceLine(units) {
    const employers = [...new Set(units.map((row) => row.employer))];
    const cities = [...new Set(units.map((row) => row.city))];
    if (employers.length === 1) return `${employers[0]} · ${cities.join(", ")}`;
    return `${employers.length} workplaces`;
  }

  function paint() {
    const city = $("union-city").value;
    const sector = $("union-sector").value;
    const status = $("union-status").value;
    const query = $("union-search").value.trim().toLowerCase();
    const matched = rows.filter((row) => {
      if (city && row.city !== city) return false;
      if (sector && row.sector !== sector) return false;
      if (status && row.status !== status) return false;
      if (!query) return true;
      return [row.union, row.employer, row.unit, row.industry].join(" ").toLowerCase().includes(query);
    });
    $("union-list").innerHTML = groupRows(matched)
      .map((group) => {
        const units = group.units
          .map((row) => {
            const href = linkTarget(row.source) || linkTarget(row.contact);
            const link = href ? `<p><a href="${esc(href)}">Source</a></p>` : "";
            const workers = row.workers ? `${count(row.workers)} workers` : row.status;
            return `<li>
              <strong>${esc(row.unit)}</strong>
              <p class="hint">${esc(row.employer)} · ${esc(row.city)}. ${esc(workers)}. ${esc(row.count_basis || "")}</p>
              <p class="hint">${esc(row.sector)} · ${esc(row.industry)}</p>
              ${row.notes ? `<p class="hint">${esc(row.notes)}</p>` : ""}
              ${link}
            </li>`;
          })
          .join("");
        const badge = group.units.length > 1 ? `${group.units.length} units` : (group.units[0].workers ? count(group.units[0].workers) : group.units[0].status);
        return `<details class="union-row">
          <summary>
            <strong>${esc(group.union)}</strong>
            <span class="workplace">${esc(workplaceLine(group.units))}</span>
            <span class="badge">${esc(badge)}</span>
          </summary>
          <ul class="unit-list">${units}</ul>
        </details>`;
      })
      .join("");
  }

  ["union-city", "union-sector", "union-status"].forEach((id) => $(id).addEventListener("change", paint));
  $("union-search").addEventListener("input", paint);
  paint();
}

async function main() {
  await loadMapConfig();
  const response = await fetch("data/yolo-profile.json");
  if (!response.ok) throw new Error("Missing profile data");
  const profile = await response.json();
  renderSnapshot(profile);
  renderPeople(profile);
  renderIncome(profile);
  renderWork(profile);
  renderUnions(profile);
  if (window.L) renderMap(profile);
}

main().catch((error) => {
  document.querySelector(".profile").insertAdjacentHTML(
    "afterbegin",
    `<p class="status" data-tone="error">${esc(error.message)}</p>`
  );
});
