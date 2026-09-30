const API_BASE = "http://127.0.0.1:5000";
const SESSION_KEY = "athletics_session_id";
const HISTORY_KEY = "athletics_chat_history";

const chatArea = document.getElementById("chat-area");
const userInput = document.getElementById("user-input");
const btnSend = document.getElementById("btn-send");
const btnCompeting = document.getElementById("btn-competing");
const statusText = document.getElementById("status-text");

// Persistent session ID — survives popup close/reopen
let sessionId;

// Load session, chat history, medals, and pending results on popup open
chrome.storage.local.get(
  [SESSION_KEY, HISTORY_KEY, "lastMedalCheck",
   "athletics_new_medal_keys", "lastNewMedals",
   "pendingChatResponse", "pendingCompetitionsResponse", "pendingUpcomingResponse",
   "pending_chat", "pending_competitions", "pending_upcoming"],
  (result) => {
    if (result[SESSION_KEY]) {
      sessionId = result[SESSION_KEY];
    } else {
      sessionId = "chrome_ext_" + Date.now();
      chrome.storage.local.set({ [SESSION_KEY]: sessionId });
    }

    // Restore chat history (skip competition entries — they're live data)
    const history = (result[HISTORY_KEY] || []).filter((msg) => msg.type !== "competition");
    if (history.length > 0) {
      chatArea.innerHTML = "";
      history.forEach((msg) => {
        appendBubble(msg.text, msg.type);
      });
    }

    // Show medal banner
    const medalData = result.lastMedalCheck;
    const newMedalKeys = result.athletics_new_medal_keys || [];
    const lastNewMedals = result.lastNewMedals || [];

    if (medalData && medalData.medals && medalData.medals.length > 0) {
      // Always show banner when medal data exists
      showMedalBanner(medalData.medals, newMedalKeys, lastNewMedals);
      // Acknowledge new medals — clears new keys and updates badge
      if (newMedalKeys.length > 0) {
        chrome.runtime.sendMessage({ type: "acknowledgeNewMedals" }).catch(() => {});
      }
    }

    // Ensure inputs start enabled (clean slate)
    setLoading(false);
    btnCompeting.disabled = false;
    btnUpcoming.disabled = false;

    // Pick up results that arrived while popup was closed
    if (result.pendingChatResponse) {
      handleChatResult(result.pendingChatResponse);
      chrome.storage.local.remove("pendingChatResponse");
    } else if (result.pending_chat) {
      // Request still in flight — show thinking bubble
      setLoading(true);
      showThinkingBubble("chat");
    }

    if (result.pendingCompetitionsResponse) {
      handleCompetitionsResult(result.pendingCompetitionsResponse);
      chrome.storage.local.remove("pendingCompetitionsResponse");
    } else if (result.pending_competitions) {
      showThinkingBubble("competitions");
      btnCompeting.disabled = true;
    }

    if (result.pendingUpcomingResponse) {
      handleUpcomingResult(result.pendingUpcomingResponse);
      chrome.storage.local.remove("pendingUpcomingResponse");
    } else if (result.pending_upcoming) {
      showThinkingBubble("upcoming");
      btnUpcoming.disabled = true;
    }
  }
);

// Listen for results from background service worker
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "chatResult") {
    handleChatResult(msg.data);
    chrome.storage.local.remove("pendingChatResponse");
  } else if (msg.type === "competitionsResult") {
    handleCompetitionsResult(msg.data);
    chrome.storage.local.remove("pendingCompetitionsResponse");
  } else if (msg.type === "upcomingResult") {
    handleUpcomingResult(msg.data);
    chrome.storage.local.remove("pendingUpcomingResponse");
  }
});

// Listen for medal data arriving while popup is open
chrome.storage.onChanged.addListener((changes) => {
  if (changes.lastMedalCheck && changes.lastMedalCheck.newValue) {
    const medalData = changes.lastMedalCheck.newValue;
    const newMedals = changes.lastNewMedals ? changes.lastNewMedals.newValue || [] : [];
    if (medalData.medals && medalData.medals.length > 0) {
      // Read lastNewMedals from storage since it may have been set in the same write
      chrome.storage.local.get(["lastNewMedals", "athletics_new_medal_keys"], (result) => {
        showMedalBanner(medalData.medals, result.athletics_new_medal_keys || [], result.lastNewMedals || []);
        if ((result.athletics_new_medal_keys || []).length > 0) {
          chrome.runtime.sendMessage({ type: "acknowledgeNewMedals" }).catch(() => {});
        }
      });
    }
  }
});

const btnClear = document.getElementById("btn-clear");
const btnUpcoming = document.getElementById("btn-upcoming");

btnSend.addEventListener("click", sendMessage);
userInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});
btnCompeting.addEventListener("click", checkCompetitions);
btnUpcoming.addEventListener("click", checkUpcoming);
btnClear.addEventListener("click", clearChat);

function sendMessage() {
  const message = userInput.value.trim();
  if (!message) return;

  addMessage(message, "user");
  userInput.value = "";
  setLoading(true);
  showThinkingBubble("chat");

  // Send to background worker — survives popup close
  chrome.runtime.sendMessage({ type: "chat", message, session_id: sessionId });
}

function handleChatResult(data) {
  removeThinkingBubble();
  setLoading(false);

  if (data.error) {
    addMessage("Error: " + data.error, "error");
  } else {
    const cleaned = cleanMarkdown(data.response);
    if (looksLikeAthleteProfile(cleaned)) {
      renderAthleteCard(cleaned);
    } else {
      addMessage(cleaned, "bot");
    }
  }
}

function checkCompetitions() {
  btnCompeting.disabled = true;
  setStatus("Checking competitions...");
  showThinkingBubble("competitions");

  chrome.runtime.sendMessage({ type: "competitions" });
}

function handleCompetitionsResult(data) {
  removeThinkingBubble();
  btnCompeting.disabled = false;
  setStatus("");

  if (data.error) {
    addMessage("Error: " + data.error, "error");
  } else if (!data.competitions || data.competitions.length === 0) {
    addMessage("No current competition data found. Try again later.", "competition");
  } else {
    data.competitions.forEach((comp) => {
      if (comp.error) return;
      renderCompetitionCard(comp);
    });
  }
}

function checkUpcoming() {
  btnUpcoming.disabled = true;
  setStatus("Checking upcoming events...");
  showThinkingBubble("upcoming");

  chrome.runtime.sendMessage({ type: "upcoming" });
}

function handleUpcomingResult(data) {
  removeThinkingBubble();
  btnUpcoming.disabled = false;
  setStatus("");

  if (data.error) {
    addMessage("Error: " + data.error, "error");
  } else if (!data.upcoming || data.upcoming.length === 0) {
    addMessage("No upcoming athletics competitions found in the next 12 months.", "bot");
  } else {
    data.upcoming.forEach((comp) => {
      renderUpcomingCard(comp);
    });
  }
}

function renderUpcomingCard(comp) {
  const card = document.createElement("div");
  card.className = "message bot upcoming-card";

  // Title
  const title = document.createElement("div");
  title.className = "upcoming-title";
  title.textContent = comp.competition;
  card.appendChild(title);

  // Dates and location
  const subtitleParts = [];
  if (comp.dates) subtitleParts.push(comp.dates);
  if (comp.location) subtitleParts.push(comp.location);
  if (subtitleParts.length > 0) {
    const subtitle = document.createElement("div");
    subtitle.className = "upcoming-subtitle";
    subtitle.textContent = subtitleParts.join(" \u00B7 ");
    card.appendChild(subtitle);
  }

  // Participation status badge
  const statusBadge = document.createElement("div");
  statusBadge.className = "upcoming-status";
  if (comp.participation === "confirmed") {
    statusBadge.classList.add("upcoming-status-confirmed");
    statusBadge.textContent = "Indian participation confirmed";
  } else if (comp.participation === "potential") {
    statusBadge.classList.add("upcoming-status-potential");
    statusBadge.textContent = "Potential Indian athletes (based on recent competitions)";
  } else {
    statusBadge.classList.add("upcoming-status-pending");
    statusBadge.textContent = "Indian participation pending";
  }
  card.appendChild(statusBadge);

  // Events with athletes (if confirmed)
  if (comp.events && comp.events.length > 0) {
    comp.events.forEach((evt) => {
      const eventBlock = document.createElement("div");
      eventBlock.className = "upcoming-event";

      const eventName = document.createElement("div");
      eventName.className = "upcoming-event-name";
      eventName.textContent = evt.event;
      eventBlock.appendChild(eventName);

      if (evt.athletes && evt.athletes.length > 0) {
        const names = evt.athletes.map((a) => a.name).join(", ");
        const athleteList = document.createElement("div");
        athleteList.className = "upcoming-athletes";
        athleteList.textContent = names;
        eventBlock.appendChild(athleteList);
      }

      card.appendChild(eventBlock);
    });
  }

  chatArea.appendChild(card);
  card.scrollIntoView({ behavior: "smooth", block: "start" });
}

function addMessage(text, type) {
  appendBubble(text, type);
  saveToHistory(text, type);
}

function appendBubble(text, type) {
  const div = document.createElement("div");
  div.className = `message ${type}`;
  div.textContent = text;
  chatArea.appendChild(div);
  div.scrollIntoView({ behavior: "smooth", block: "start" });
}

function saveToHistory(text, type) {
  chrome.storage.local.get([HISTORY_KEY], (result) => {
    const history = result[HISTORY_KEY] || [];
    history.push({ text, type });
    // Keep last 50 messages to avoid storage bloat
    if (history.length > 50) history.splice(0, history.length - 50);
    chrome.storage.local.set({ [HISTORY_KEY]: history });
  });
}

function cleanMarkdown(text) {
  // Strip markdown formatting that doesn't render in plain text
  return text
    .replace(/\*\*\*(.*?)\*\*\*/g, "$1")  // ***bold italic***
    .replace(/\*\*(.*?)\*\*/g, "$1")       // **bold**
    .replace(/\*(.*?)\*/g, "$1")           // *italic*
    .replace(/^#{1,6}\s+/gm, "")           // # headings
    .replace(/`([^`]+)`/g, "$1")           // `code`
    .trim();
}

function setLoading(loading) {
  btnSend.disabled = loading;
  userInput.disabled = loading;
  setStatus(loading ? "Thinking..." : "");
}

// Thinking bubble with animated dots and cycling status messages
let thinkingInterval = null;

const STATUS_MESSAGES = {
  chat: [
    "Looking up athlete info...",
    "Getting the data...",
    "Analyzing results...",
    "Almost there...",
  ],
  competitions: [
    "Getting competition data...",
    "Checking Indian athletes...",
    "Loading results...",
  ],
  upcoming: [
    "Getting event schedules...",
    "Matching athletes to disciplines...",
    "Loading upcoming events...",
  ],
};

function showThinkingBubble(mode) {
  removeThinkingBubble();

  const bubble = document.createElement("div");
  bubble.className = "message thinking-bubble";
  bubble.id = "thinking-bubble";

  const dots = document.createElement("div");
  dots.className = "thinking-dots";
  dots.innerHTML = "<span></span><span></span><span></span>";
  bubble.appendChild(dots);

  const status = document.createElement("div");
  status.className = "thinking-status";
  status.id = "thinking-status";
  const messages = STATUS_MESSAGES[mode] || STATUS_MESSAGES.chat;
  status.textContent = messages[0];
  bubble.appendChild(status);

  chatArea.appendChild(bubble);
  bubble.scrollIntoView({ behavior: "smooth", block: "start" });

  let index = 0;
  thinkingInterval = setInterval(() => {
    index = (index + 1) % messages.length;
    const el = document.getElementById("thinking-status");
    if (el) {
      el.style.opacity = "0";
      setTimeout(() => {
        el.textContent = messages[index];
        el.style.opacity = "1";
      }, 150);
    }
  }, 2500);
}

function removeThinkingBubble() {
  if (thinkingInterval) {
    clearInterval(thinkingInterval);
    thinkingInterval = null;
  }
  const existing = document.getElementById("thinking-bubble");
  if (existing) existing.remove();
}

function clearChat() {
  // Reset session ID so server starts fresh conversation
  sessionId = "chrome_ext_" + Date.now();
  chrome.storage.local.set({
    [SESSION_KEY]: sessionId,
    [HISTORY_KEY]: [],
  });
  // Clear any stale pending flags
  chrome.storage.local.remove([
    "pending_chat", "pending_competitions", "pending_upcoming",
    "pendingChatResponse", "pendingCompetitionsResponse", "pendingUpcomingResponse",
  ]);
  removeThinkingBubble();
  setLoading(false);
  btnCompeting.disabled = false;
  btnUpcoming.disabled = false;
  chatArea.innerHTML = "";
  appendBubble(
    "Namaste! I'm BhagYahanSe \u2014 your guide to Indians in athletics. Ask me about any athlete, check who's competing right now, or see what's coming up next.",
    "bot"
  );
}

function looksLikeAthleteProfile(text) {
  // Detect if the response is about a SINGLE athlete (not a competition summary)
  const lower = text.toLowerCase();

  // Reject if this looks like a competition/event summary (multiple athletes mentioned)
  const antiSignals = ["competing", "competition", "asian games", "currently happening",
    "right now", "athletes are", "medal tally", "events are", "who is competing",
    "upcoming", "schedule", "indian athletes"];
  for (const s of antiSignals) {
    if (lower.includes(s)) return false;
  }

  const signals = ["personal best", "achievements", "gold medal", "olympic", "world championships",
    "javelin", "sprint", "100m", "200m", "400m", "800m", "1500m", "high jump", "long jump",
    "shot put", "discus", "steeplechase", "marathon", "pole vault", "decathlon", "heptathlon"];
  let score = 0;
  signals.forEach((s) => { if (lower.includes(s)) score++; });
  return score >= 2;
}

function renderAthleteCard(text) {
  const card = document.createElement("div");
  card.className = "message bot athlete-card";

  // Extract name from first line/sentence
  const name = extractName(text);
  const event = extractField(text, ["javelin throw", "javelin", "100m", "200m", "400m", "800m",
    "1500m", "5000m", "10000m", "10,000m", "marathon", "hurdles", "steeplechase",
    "high jump", "long jump", "triple jump", "pole vault", "shot put", "discus throw",
    "discus", "hammer throw", "hammer", "decathlon", "heptathlon", "race walk", "sprinter",
    "sprint", "relay"]);
  const pbs = extractPBs(text);

  // Header
  const hdr = document.createElement("div");
  hdr.className = "card-header";
  hdr.innerHTML = `<div class="card-name">${name}</div><div class="card-event">${event}</div>`;
  card.appendChild(hdr);

  // Stats row — show all PBs
  if (pbs.length > 0) {
    const stats = document.createElement("div");
    stats.className = "card-stats";
    pbs.forEach((pb) => {
      const stat = document.createElement("div");
      stat.className = "card-stat";
      const label = pb.event ? `PB — ${pb.event}` : "PERSONAL BEST";
      stat.innerHTML = `<div class="stat-value">${pb.value}</div><div class="stat-label">${label}</div>`;
      stats.appendChild(stat);
    });
    card.appendChild(stats);
  }

  // Achievements — extract bullet points
  const achievements = extractAchievements(text);
  if (achievements.length > 0) {
    const pills = document.createElement("div");
    pills.className = "card-pills";
    achievements.forEach((a) => {
      const pill = document.createElement("span");
      pill.className = "card-pill";
      pill.textContent = a;
      pills.appendChild(pill);
    });
    card.appendChild(pills);
  }

  // Summary — first sentence or two
  const summary = extractSummary(text);
  if (summary) {
    const desc = document.createElement("div");
    desc.className = "card-summary";
    desc.textContent = summary;
    card.appendChild(desc);
  }

  chatArea.appendChild(card);
  card.scrollIntoView({ behavior: "smooth", block: "start" });
  saveToHistory(text, "bot");
}

function extractName(text) {
  // First line usually has the athlete name
  const firstLine = text.split("\n")[0];
  // Look for a capitalized name (two+ capitalized words)
  const nameMatch = firstLine.match(/([A-Z][a-z]+ [A-Z][a-z]+(?:\s[A-Z][a-z]+)?)/);
  if (nameMatch) return nameMatch[1];
  // Fallback: first 30 chars of first line
  return firstLine.substring(0, 30);
}

function extractField(text, keywords) {
  const lower = text.toLowerCase();
  for (const kw of keywords) {
    if (lower.includes(kw)) {
      return kw.charAt(0).toUpperCase() + kw.slice(1);
    }
  }
  return "Athletics";
}

function extractPBs(text) {
  // Extract multiple PBs — returns [{event, value}]
  const pbs = [];
  const lines = text.split("\n");

  for (const line of lines) {
    // Match patterns like "10,000m PB: 28:17.22" or "5000m - Personal Best: 13:18.92"
    // or "Javelin Throw: 88.17m (PB)" or "10k PB: 28:17" or "100m: 10.36 (PB)"
    const pbLine = line.match(/(\d[\d,]*\s*m(?:eters?)?|[\w\s]+(?:throw|jump|walk|vault|put|marathon|relay|hurdles|steeplechase|decathlon|heptathlon))\s*[-:–]\s*(?:personal best[:\s]*|pb[:\s]*)?(\d[\d:.]+\s*(?:m(?:eters?)?|s(?:econds?)?)?(?:\s*(?:PB|SB|NR))?)/i);
    if (pbLine) {
      let event = pbLine[1].trim();
      let value = pbLine[2].trim();
      // Normalize event name
      event = event.replace(/,/g, "");
      if (event.length > 25) event = event.substring(0, 25);
      if (value.length > 20) value = value.substring(0, 20);
      pbs.push({ event, value });
    }

    // Also match "Personal Best: X" on its own line (single-event athletes)
    if (pbs.length === 0) {
      const singlePB = line.match(/personal best[:\s]+(\d[\d:.]+\s*(?:m(?:eters?)?)?(?:\s*(?:PB|SB|NR))?)/i);
      if (singlePB) {
        pbs.push({ event: "", value: singlePB[1].trim() });
      }
    }
  }

  // Fallback: find any time/distance if no structured PBs found
  if (pbs.length === 0) {
    const numMatch = text.match(/(\d+\.\d+\s*m(?:eters?)?)/i);
    if (numMatch) return [{ event: "", value: numMatch[1] }];
    const timeMatch = text.match(/(\d{1,2}:\d{2}\.\d+)/);
    if (timeMatch) return [{ event: "", value: timeMatch[1] }];
  }

  // Deduplicate by event
  const seen = new Set();
  return pbs.filter((p) => {
    const key = p.event.toLowerCase() + p.value;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, 5);
}

function extractAchievements(text) {
  const achievements = [];
  // Match lines starting with - or bullet patterns
  const lines = text.split("\n");
  lines.forEach((line) => {
    const trimmed = line.trim();
    if (trimmed.startsWith("-") || trimmed.startsWith("•")) {
      let item = trimmed.replace(/^[-•]\s*/, "").trim();
      // Remove emoji characters
      item = item.replace(/[\u{1F3C5}\u{1F3C6}\u{1F947}\u{1F948}\u{1F949}\u{1F3C3}]/gu, "").trim();
      if (item.length > 3 && item.length < 80) {
        achievements.push(item);
      }
    }
  });
  return achievements.slice(0, 6);
}

function extractSummary(text) {
  // Get first sentence or two (before achievements list)
  const lines = text.split("\n");
  let summary = "";
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    if (trimmed.startsWith("-") || trimmed.startsWith("•")) break;
    if (trimmed.toLowerCase().includes("achievement") || trimmed.toLowerCase().includes("here's what")) continue;
    summary += trimmed + " ";
    if (summary.length > 150) break;
  }
  summary = summary.trim();
  if (summary.length > 200) summary = summary.substring(0, 197) + "...";
  return summary;
}

function renderCompetitionCard(comp) {
  const card = document.createElement("div");
  card.className = "message bot competition-card";

  // Competition title
  const title = document.createElement("div");
  title.className = "comp-title";
  title.textContent = comp.competition;
  card.appendChild(title);

  // Dates and location subtitle
  const subtitleParts = [];
  if (comp.dates) subtitleParts.push(comp.dates);
  if (comp.location) subtitleParts.push(comp.location);
  if (subtitleParts.length > 0) {
    const subtitle = document.createElement("div");
    subtitle.className = "comp-subtitle";
    subtitle.textContent = subtitleParts.join(" · ");
    card.appendChild(subtitle);
  }

  if (comp.events && comp.events.length > 0) {
    comp.events.forEach((evt) => {
      const eventBlock = document.createElement("div");
      eventBlock.className = "comp-event";

      const eventName = document.createElement("div");
      eventName.className = "comp-event-name";
      eventName.textContent = evt.event;
      eventBlock.appendChild(eventName);

      evt.athletes.forEach((a) => {
        const row = document.createElement("div");
        row.className = "comp-athlete-row";
        if (a.medal) row.classList.add("comp-medal-" + a.medal.toLowerCase());

        let nameHtml = a.name;
        if (a.medal) {
          const medalTag = a.medal === "Gold" ? "G" : a.medal === "Silver" ? "S" : "B";
          nameHtml = `<span class="comp-medal-tag comp-medal-${a.medal.toLowerCase()}-tag">${medalTag}</span> ${a.name}`;
        }
        let rightHtml = "";
        if (a.result) rightHtml += a.result;
        if (a.placement) {
          if (rightHtml) rightHtml += " · ";
          rightHtml += a.placement;
        }

        row.innerHTML = `<span class="comp-athlete-name">${nameHtml}</span>`;
        if (rightHtml) {
          row.innerHTML += `<span class="comp-athlete-result">${rightHtml}</span>`;
        }
        eventBlock.appendChild(row);
      });

      card.appendChild(eventBlock);
    });
  }

  chatArea.appendChild(card);
  card.scrollIntoView({ behavior: "smooth", block: "start" });
  // Competition data is live — don't save to history (goes stale)
}

function showMedalBanner(medals, newMedalKeys = [], lastNewMedals = []) {
  // Remove existing banner if any
  const existing = document.getElementById("medal-banner");
  if (existing) existing.remove();

  // Build set of new medal keys for highlighting in table
  const newKeySet = new Set(newMedalKeys);

  // Deduplicate medals — normalize sport + athlete + event for comparison
  const seen = new Set();
  const deduped = [];
  medals.forEach((m) => {
    const sport = (m.sport || "").toLowerCase().trim();
    const athlete = m.athlete.split(",")[0].trim().toLowerCase();
    const event = (m.event || "").toLowerCase()
      .replace(/\s+/g, " ").replace(/×/g, "x").replace(/ x /g, "x")
      .replace(/\d+\s*m\b/g, (match) => match.replace(/\s/g, ""));
    const key = `${m.medal}|${sport}|${athlete}|${event}`;
    if (!seen.has(key)) {
      seen.add(key);
      deduped.push(m);
    }
  });

  const banner = document.createElement("div");
  banner.id = "medal-banner";
  banner.className = "medal-banner";

  // Group medals by competition
  const byComp = {};
  deduped.forEach((m) => {
    const comp = m.competition || "Competition";
    if (!byComp[comp]) byComp[comp] = [];
    byComp[comp].push(m);
  });

  Object.entries(byComp).forEach(([comp, compMedals]) => {
    const gold = compMedals.filter((m) => m.medal === "Gold").length;
    const silver = compMedals.filter((m) => m.medal === "Silver").length;
    const bronze = compMedals.filter((m) => m.medal === "Bronze").length;
    const total = compMedals.length;

    // Clean competition name (remove year prefix for brevity)
    const compName = comp.replace(/^\d{4}\s+/, "");

    // Summary line — clickable to expand/collapse full table
    const summary = document.createElement("div");
    summary.className = "medal-summary";
    summary.innerHTML = `<span class="medal-arrow">&#9654;</span> India @ ${compName}: ${gold}G ${silver}S ${bronze}B <span class="medal-total">(${total} total)</span>`;

    // Build full medal table (hidden by default)
    const table = document.createElement("table");
    table.className = "medal-table";

    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");
    ["", "Sport", "Event", "Athlete"].forEach((text) => {
      const th = document.createElement("th");
      th.textContent = text;
      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    const medalEmoji = { Gold: "\uD83E\uDD47", Silver: "\uD83E\uDD48", Bronze: "\uD83E\uDD49" };

    ["Gold", "Silver", "Bronze"].forEach((type) => {
      compMedals.filter((m) => m.medal === type).forEach((m) => {
        const tr = document.createElement("tr");
        const mKey = `${m.medal}_${m.sport || "Athletics"}_${m.event}_${m.athlete}`;
        if (newKeySet.has(mKey)) tr.className = "medal-new";

        const tdMedal = document.createElement("td");
        tdMedal.textContent = medalEmoji[type] || "";
        tr.appendChild(tdMedal);

        const tdSport = document.createElement("td");
        tdSport.textContent = m.sport || "";
        tr.appendChild(tdSport);

        const tdEvent = document.createElement("td");
        tdEvent.textContent = m.event || "";
        tr.appendChild(tdEvent);

        const tdAthlete = document.createElement("td");
        const athlete = m.athlete.split(",")[0].trim();
        const relay = m.athlete.includes(",") ? " + team" : "";
        tdAthlete.textContent = `${athlete}${relay}`;
        tr.appendChild(tdAthlete);

        tbody.appendChild(tr);
      });
    });

    table.appendChild(tbody);

    // Click summary to toggle full table
    summary.addEventListener("click", () => {
      const isExpanded = table.classList.toggle("expanded");
      summary.querySelector(".medal-arrow").innerHTML = isExpanded ? "&#9660;" : "&#9654;";
    });

    banner.appendChild(summary);
    banner.appendChild(table);
  });

  // Updates section — always visible below banner, shows recent medal updates
  if (lastNewMedals.length > 0) {
    const updatesDiv = document.createElement("div");
    updatesDiv.className = "medal-updates";

    const updatesHeaderRow = document.createElement("div");
    updatesHeaderRow.className = "medal-updates-header-row";

    const updatesHeader = document.createElement("span");
    updatesHeader.className = "medal-updates-header";
    updatesHeader.textContent = "Recent updates";
    updatesHeaderRow.appendChild(updatesHeader);

    const updatesClose = document.createElement("span");
    updatesClose.className = "medal-updates-close";
    updatesClose.textContent = "\u00D7";
    updatesClose.addEventListener("click", () => {
      updatesDiv.remove();
      // Clear stored updates so they don't reappear on next popup open
      chrome.storage.local.set({ lastNewMedals: [] });
    });
    updatesHeaderRow.appendChild(updatesClose);

    updatesDiv.appendChild(updatesHeaderRow);

    lastNewMedals.forEach((m) => {
      const line = document.createElement("div");
      line.className = "medal-update-line";
      const eventLower = (m.event || "").toLowerCase();
      const isTeamEvent = eventLower.includes("relay") || eventLower.includes("team") || eventLower.includes("tournament");

      let who;
      if (isTeamEvent) {
        // Determine Men's/Women's/Mixed from event name
        if (eventLower.includes("mixed")) who = "Mixed team";
        else if (eventLower.includes("women") || eventLower.includes("female")) who = "Women's team";
        else if (eventLower.includes("men") || eventLower.includes("male")) who = "Men's team";
        else who = "India team";
      } else {
        who = (m.athlete || "").split(",")[0].trim();
      }

      const sport = m.sport ? ` ${m.sport}` : "";
      const medalLower = (m.medal || "").toLowerCase();
      line.textContent = `\u2022 ${who} wins ${medalLower} in${sport} — ${m.event}`;
      updatesDiv.appendChild(line);
    });

    banner.appendChild(updatesDiv);
  }

  // Insert after header
  const header = document.querySelector(".header");
  header.after(banner);
}

function setStatus(text) {
  statusText.textContent = text;
}
