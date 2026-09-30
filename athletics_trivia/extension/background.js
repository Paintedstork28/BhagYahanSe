const API_BASE = "http://127.0.0.1:5000";
const IDLE_INTERVAL = 360;  // 6 hours — check if any competition is active
const ACTIVE_INTERVAL = 60; // 1 hour — check for new medals during active competition
const SEEN_MEDALS_KEY = "athletics_seen_medals";
const NEW_MEDALS_KEY = "athletics_new_medal_keys";
const DISMISSED_KEY = "athletics_banner_dismissed";
const ACTIVE_MODE_KEY = "athletics_active_mode";

// Clear stale state on service worker startup (extension reload/update)
chrome.storage.local.remove([
  "pending_chat", "pending_competitions", "pending_upcoming",
  "pendingChatResponse", "pendingCompetitionsResponse", "pendingUpcomingResponse",
  "athletics_chat_history", "athletics_session_id",
  DISMISSED_KEY,  // Reset dismissed flag on reload
  "lastNewMedals",  // Clear stale updates on reload
]);

// Set up alarms on install AND on every service worker startup
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("checkCompetitions", {
    delayInMinutes: 1,
    periodInMinutes: IDLE_INTERVAL,
  });
});

// On every startup (reload, wake-up): ensure alarms exist and do immediate check
chrome.alarms.get("checkCompetitions", (alarm) => {
  if (!alarm) {
    chrome.alarms.create("checkCompetitions", {
      delayInMinutes: 1,
      periodInMinutes: IDLE_INTERVAL,
    });
  }
});

// Immediate medal check on startup via short alarm (keeps service worker alive)
chrome.alarms.create("startupMedalCheck", { delayInMinutes: 0.05 });

// Handle alarms
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "checkCompetitions") {
    checkForActiveCompetition();
  } else if (alarm.name === "checkMedals" || alarm.name === "startupMedalCheck") {
    checkForNewMedals();
  }
});

// IDLE MODE: Check if any competition is active
async function checkForActiveCompetition() {
  try {
    const response = await fetch(`${API_BASE}/api/competitions`);
    if (!response.ok) return;

    const data = await response.json();
    const hasCompetitions = data.competitions && data.competitions.length > 0;

    chrome.storage.local.get([ACTIVE_MODE_KEY], (result) => {
      const wasActive = result[ACTIVE_MODE_KEY] || false;

      if (hasCompetitions && !wasActive) {
        // Competition found — switch to active mode
        chrome.storage.local.set({ [ACTIVE_MODE_KEY]: true });
        chrome.alarms.create("checkMedals", {
          delayInMinutes: 0.5, // first medal check in 30 seconds
          periodInMinutes: ACTIVE_INTERVAL,
        });
        // Also do an immediate medal check
        checkForNewMedals();
      } else if (!hasCompetitions && wasActive) {
        // Competition over — switch back to idle mode
        chrome.storage.local.set({ [ACTIVE_MODE_KEY]: false });
        chrome.alarms.clear("checkMedals");
      }
    });
  } catch (err) {
    // Server not running — silently skip
  }
}

// ACTIVE MODE: Check for new medals
async function checkForNewMedals() {
  try {
    const response = await fetch(`${API_BASE}/api/all-medals`);
    if (!response.ok) return;

    const data = await response.json();
    if (!data.medals || data.medals.length === 0) return;

    // Load previously seen medals and existing new-medal keys
    chrome.storage.local.get([SEEN_MEDALS_KEY, NEW_MEDALS_KEY, DISMISSED_KEY], (result) => {
      const previousKeys = result[SEEN_MEDALS_KEY] || [];
      const seenKeys = new Set(previousKeys);
      const isFirstCheck = previousKeys.length === 0;
      const existingNewKeys = result[NEW_MEDALS_KEY] || [];

      // Find new medals
      const newMedals = [];
      const newKeys = [];
      const allKeys = [];

      data.medals.forEach((medal) => {
        const key = `${medal.medal}_${medal.sport || "Athletics"}_${medal.event}_${medal.athlete}`;
        allKeys.push(key);
        if (!seenKeys.has(key)) {
          newMedals.push(medal);
          newKeys.push(key);
        }
      });

      // Accumulate new keys (don't replace — popup clears them on open)
      const allNewKeys = [...new Set([...existingNewKeys, ...newKeys])];

      // Only send OS notifications if this isn't the first check
      if (!isFirstCheck && newMedals.length > 0) {
        // Reset dismissed flag — new medals should show the banner again
        chrome.storage.local.set({ [DISMISSED_KEY]: false });

        newMedals.forEach((medal, i) => {
          const emoji = medal.medal === "Gold" ? "GOLD" :
                        medal.medal === "Silver" ? "SILVER" : "BRONZE";
          const sport = medal.sport ? ` (${medal.sport})` : "";

          chrome.notifications.create(`medal-${Date.now()}-${i}`, {
            type: "basic",
            iconUrl: "icons/icon128.png",
            title: `${emoji}: ${medal.athlete}`,
            message: `${medal.medal} in ${medal.event}${sport}${medal.date ? " — " + medal.date : ""}`,
            priority: 2,
          });
        });
      }

      // Badge: show new medal count if any, else total
      if (allNewKeys.length > 0) {
        chrome.action.setBadgeText({ text: String(allNewKeys.length) });
        chrome.action.setBadgeBackgroundColor({ color: "#27ae60" }); // green for new
      } else if (data.medals.length > 0) {
        chrome.action.setBadgeText({ text: String(data.medals.length) });
        chrome.action.setBadgeBackgroundColor({ color: "#FFD700" }); // gold for total
      }

      // Store medal updates for the banner's "Recent updates" section
      // Only update lastNewMedals when there are actually new medals
      const storeData = {
        [SEEN_MEDALS_KEY]: allKeys,
        [NEW_MEDALS_KEY]: allNewKeys,
        lastMedalCheck: data,
        lastMedalCheckTime: new Date().toISOString(),
      };
      if (newMedals.length > 0) {
        storeData.lastNewMedals = newMedals;
      }
      chrome.storage.local.set(storeData);
    });
  } catch (err) {
    // Server not running — silently skip
  }
}

// Open popup when notification clicked
chrome.notifications.onClicked.addListener(() => {
  chrome.action.openPopup();
});


// ── API proxy for popup ──────────────────────────────────────────────
// Popup sends messages here so requests survive popup close/reopen.

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "chat") {
    handleChat(msg).then(() => sendResponse({ done: true }));
    return true;
  } else if (msg.type === "competitions") {
    handleCompetitions().then(() => sendResponse({ done: true }));
    return true;
  } else if (msg.type === "upcoming") {
    handleUpcoming().then(() => sendResponse({ done: true }));
    return true;
  } else if (msg.type === "acknowledgeNewMedals") {
    // Popup opened and displayed new medals — clear new keys, update badge to total
    chrome.storage.local.get(["lastMedalCheck"], (result) => {
      const totalMedals = result.lastMedalCheck?.medals?.length || 0;
      chrome.storage.local.set({ [NEW_MEDALS_KEY]: [] });
      if (totalMedals > 0) {
        chrome.action.setBadgeText({ text: String(totalMedals) });
        chrome.action.setBadgeBackgroundColor({ color: "#FFD700" });
      }
    });
    sendResponse({ done: true });
    return false;
  } else if (msg.type === "dismissMedals") {
    // User clicked ✕ — hide banner and clear badge
    chrome.storage.local.set({ [DISMISSED_KEY]: true, [NEW_MEDALS_KEY]: [] });
    chrome.action.setBadgeText({ text: "" });
    sendResponse({ done: true });
    return false;
  }
  return false;
});

async function handleChat(msg) {
  chrome.storage.local.set({ pending_chat: true });
  try {
    const response = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: msg.message, session_id: msg.session_id }),
    });
    if (!response.ok) throw new Error(`Server error: ${response.status}`);
    const data = await response.json();
    chrome.storage.local.set({ pendingChatResponse: data, pending_chat: false });
    // Notify popup if it's open
    chrome.runtime.sendMessage({ type: "chatResult", data }).catch(() => {});
  } catch (err) {
    const error = err.message.includes("Failed to fetch") || err.message.includes("NetworkError")
      ? "Cannot reach the server. Make sure the Flask API is running:\npython -m athletics_trivia.server"
      : err.message;
    chrome.storage.local.set({ pendingChatResponse: { error }, pending_chat: false });
    chrome.runtime.sendMessage({ type: "chatResult", data: { error } }).catch(() => {});
  }
}

async function handleCompetitions() {
  chrome.storage.local.set({ pending_competitions: true });
  try {
    const response = await fetch(`${API_BASE}/api/competitions`);
    if (!response.ok) throw new Error(`Server error: ${response.status}`);
    const data = await response.json();
    chrome.storage.local.set({ pendingCompetitionsResponse: data, pending_competitions: false });
    chrome.runtime.sendMessage({ type: "competitionsResult", data }).catch(() => {});
  } catch (err) {
    const error = err.message.includes("Failed to fetch") || err.message.includes("NetworkError")
      ? "Cannot reach the server. Make sure the Flask API is running:\npython -m athletics_trivia.server"
      : err.message;
    chrome.storage.local.set({ pendingCompetitionsResponse: { error }, pending_competitions: false });
    chrome.runtime.sendMessage({ type: "competitionsResult", data: { error } }).catch(() => {});
  }
}

async function handleUpcoming() {
  chrome.storage.local.set({ pending_upcoming: true });
  try {
    const response = await fetch(`${API_BASE}/api/upcoming`);
    if (!response.ok) throw new Error(`Server error: ${response.status}`);
    const data = await response.json();
    chrome.storage.local.set({ pendingUpcomingResponse: data, pending_upcoming: false });
    chrome.runtime.sendMessage({ type: "upcomingResult", data }).catch(() => {});
  } catch (err) {
    const error = err.message.includes("Failed to fetch") || err.message.includes("NetworkError")
      ? "Cannot reach the server. Make sure the Flask API is running:\npython -m athletics_trivia.server"
      : err.message;
    chrome.storage.local.set({ pendingUpcomingResponse: { error }, pending_upcoming: false });
    chrome.runtime.sendMessage({ type: "upcomingResult", data: { error } }).catch(() => {});
  }
}
