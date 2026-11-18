// Shows alerts for the task board and opens the task when one is clicked.
// There is no caching or offline mode: this file only exists so the browser can hand
// notifications to the operating system, both while the board is open (the page asks for them)
// and when it is closed (the server pushes them).

// A push from the server. Every push must show something (iPhone insists), so it always does,
// whether or not the board is open: on devices with push the page shows no popup of its own.
self.addEventListener("push", (event) => {
  let m = {};
  try {
    m = event.data ? event.data.json() : {};
  } catch (e) {
    m = { title: "Task Board", body: "A task changed" };
  }
  const work = [
    self.registration.showNotification(m.title || "Task Board", {
      body: m.body || "",
      tag: m.tag || undefined,
      icon: "/static/icons/icon-192.png",
      data: { taskId: m.task_id || null, id: m.id },
      // Deadlines, assignments and removals stay until dismissed (desktop; phones ignore it).
      requireInteraction: !!m.sticky,
    }),
  ];
  // The number on the app's icon, where the device supports it.
  if (typeof m.unread === "number" && self.navigator && self.navigator.setAppBadge) {
    work.push((m.unread > 0 ? self.navigator.setAppBadge(m.unread) : self.navigator.clearAppBadge()).catch(() => {}));
  }
  event.waitUntil(Promise.all(work));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const { taskId, id } = event.notification.data || {};
  const url = taskId ? "/#task-" + taskId : "/";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      const open = windows.find((w) => new URL(w.url).origin === self.location.origin);
      if (!open) return clients.openWindow(url);
      open.postMessage({ type: "open-task", taskId, id });
      return open.focus();
    })
  );
});
