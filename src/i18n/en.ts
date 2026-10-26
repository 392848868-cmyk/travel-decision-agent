const en = {
  // Header
  "app.title": "Travel Decision Agent",
  "app.subtitle": "Tell me where you are and which brands you want — I'll find the nearest mall",

  // Empty state
  "empty.title": "Travel Decision Agent",
  "empty.hint": "I'm a travel-decision assistant on EdgeOne Makers. Tell me your location and the brands you want, and I'll search nearby malls via Amap, check store availability, compare distances, and recommend one.",
  "empty.features": "Amap Search · Brand Matching · Distance Compare · Multi-turn",

  // Chat input
  "chat.placeholder": "e.g. I'm near Honglian South Road metro station, looking for a mall with both Breo and Westinghouse",
  "chat.hint": "Powered by LangGraph + Amap · Distances come from the map API",

  // Preset questions
  "preset.1": "I'm near Honglian South Road metro station. Find me a close mall that has both Breo and Westinghouse.",
  "preset.2": "If both brands don't have to be there, is there a closer option?",

  // Tool indicators
  "tool.geocode": "Geocoding",
  "tool.malls": "Nearby Malls",
  "tool.brand": "Brand Check",
  "tool.distance": "Distance",

  // Status & errors
  "status.error": "Request failed. Please check if the backend service is running.",
  "status.stopped": "⏹ *Generation stopped*",
  "status.backendError": "Backend abort request failed. The server may still be running.",

  // Debug panel
  "debug.title": "Trace",
  "debug.events": "events",
  "debug.clear": "Clear",
  "debug.empty": "Waiting for SSE events...",
  "debug.emptyHint": "After sending a message, all raw backend data will be displayed here.",

  // Conversation sidebar
  "sidebar.label": "Conversation list",
  "sidebar.title": "Chats",
  "sidebar.newChat": "New chat",
  "sidebar.loading": "Loading conversations...",
  "sidebar.loadMore": "Load more",
  "sidebar.loadingMore": "Loading...",
  "sidebar.emptyTitle": "No conversations yet",
  "sidebar.emptyHint": "Click \"New chat\" to start your first conversation.",
  "sidebar.delete": "Delete conversation",
  "sidebar.deleteConfirm": "Permanently delete this conversation? This cannot be undone.",

  // Aria labels (button hover/screen-reader)
  "aria.send": "Send",
  "aria.clearHistory": "Clear history",
  "aria.stopGeneration": "Stop generation",

  // Language toggle
  "lang.switch": "中文",

  // ─── Floating bottom-right action badges ─────────────────────────────
  "floatingLink.deploy": "Deploy",
  "floatingLink.github": "GitHub",
} as const;

export default en;
