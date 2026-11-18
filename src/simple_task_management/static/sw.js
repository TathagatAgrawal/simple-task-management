// Shows desktop alerts for the task board and opens the task when one is clicked.
// There is no caching or offline mode: this file only exists so the browser can hand
// notifications to the operating system.
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
