// Unified bridge for WebView2 (C#) and legacy QWebChannel (Python)
(function () {
  function wrapSyncBridge(syncObj) {
    if (!syncObj) return null;
    return new Proxy(syncObj, {
      get: function (target, prop) {
        if (typeof prop !== "string" || prop === "then") return target[prop];
        return function () {
          var args = Array.prototype.slice.call(arguments);
          var cb = typeof args[args.length - 1] === "function" ? args.pop() : null;
          try {
            var fn = target[prop];
            if (typeof fn !== "function") {
              var val = target[prop];
              if (cb) cb(val);
              return val;
            }
            var result = fn.apply(target, args);
            if (cb) setTimeout(function () { cb(result); }, 0);
            return result;
          } catch (e) {
            console.error("[armory-bridge]", prop, e);
            if (cb) cb(null);
            return null;
          }
        };
      }
    });
  }

  function initQtBridge(name, assign) {
    if (typeof qt === "undefined" || typeof QWebChannel === "undefined") return;
    new QWebChannel(qt.webChannelTransport, function (channel) {
      assign(channel.objects[name]);
    });
  }

  window.ArmoryBridge = {
    resolve: function (hostName, legacyName) {
      var wv = window.chrome && window.chrome.webview && window.chrome.webview.hostObjects;
      if (wv && wv.sync && wv.sync[hostName]) return wrapSyncBridge(wv.sync[hostName]);
      var legacy = null;
      initQtBridge(legacyName, function (b) { legacy = b; });
      return legacy ? wrapSyncBridge(legacy) : null;
    }
  };

  window.pyBridge = window.ArmoryBridge.resolve("bridge", "pyBridge");
  window.pyController = window.ArmoryBridge.resolve("controller", "pyController");
})();
