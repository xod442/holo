(function () {
  "use strict";

  var windows = Array.prototype.slice.call(document.querySelectorAll("[data-window]"));
  var clock = document.getElementById("desktop-clock");
  var largeClock = document.getElementById("large-clock");
  var largeDate = document.getElementById("large-date");
  var zIndex = 10;
  var calculator = { display: "0", stored: null, operator: null, replace: false };
  var ideActiveFile = "html";
  var ideDefaults = {
    html: '<main class="card">\n  <h1>Hello, Walter!</h1>\n  <p>Edit the code, then press Run.</p>\n  <button id="hello">Click me</button>\n</main>',
    css: 'body {\n  display: grid;\n  min-height: 100vh;\n  margin: 0;\n  place-items: center;\n  color: #24473f;\n  background: #dcebe4;\n  font-family: system-ui, sans-serif;\n}\n\n.card {\n  padding: 2rem;\n  border-radius: 1rem;\n  background: white;\n  box-shadow: 0 1rem 3rem #315e5533;\n}',
    js: 'document.querySelector("#hello").addEventListener("click", () => {\n  document.querySelector("h1").textContent = "It works!";\n});'
  };
  var ideFiles = {
    html: localStorage.getItem("walter.ide.html") || ideDefaults.html,
    css: localStorage.getItem("walter.ide.css") || ideDefaults.css,
    js: localStorage.getItem("walter.ide.js") || ideDefaults.js
  };

  function updateClock() {
    var now = new Date();
    clock.textContent = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(now);
    largeClock.textContent = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(now);
    largeDate.textContent = new Intl.DateTimeFormat(undefined, { weekday: "long", month: "long", day: "numeric" }).format(now);
  }

  function bringToFront(windowElement) {
    zIndex += 1;
    windowElement.style.zIndex = String(zIndex);
    windows.forEach(function (item) { item.classList.remove("is-active"); });
    windowElement.classList.add("is-active");
  }

  function updateDock() {
    document.querySelectorAll(".dock-button").forEach(function (button) {
      var target = document.getElementById(button.dataset.openWindow);
      button.classList.toggle("active", !!target && !target.hidden && !target.classList.contains("minimized"));
    });
  }

  function openWindow(id) {
    var windowElement = document.getElementById(id);
    if (!windowElement) return;
    windowElement.hidden = false;
    windowElement.classList.remove("minimized");
    bringToFront(windowElement);
    windowElement.focus({ preventScroll: true });
    updateDock();
  }

  function arrangeWindows() {
    var positions = {
      "browser-window": ["5vw", "74px"],
      "files-window": ["13%", "46vh"],
      "ide-window": ["auto", "74px"],
      "clock-window": ["auto", "auto"],
      "eyes-window": ["54%", "auto"],
      "calculator-window": ["31%", "18%"],
      "notepad-window": ["23%", "15%"],
      "terminal-window": ["25%", "18%"]
    };
    windows.forEach(function (windowElement) {
      var position = positions[windowElement.id];
      windowElement.classList.remove("minimized", "maximized");
      windowElement.hidden = false;
      windowElement.style.left = position[0];
      windowElement.style.top = position[1];
      windowElement.style.right = position[0] === "auto" ? (windowElement.id === "ide-window" ? "5%" : "24px") : "";
      if (windowElement.id === "clock-window") windowElement.style.bottom = "104px";
      if (windowElement.id === "eyes-window") windowElement.style.bottom = "95px";
      if (!["clock-window", "eyes-window"].includes(windowElement.id)) windowElement.style.bottom = "";
    });
    updateDock();
  }

  function makeDraggable(windowElement) {
    var handle = windowElement.querySelector("[data-drag-handle]");
    var startX;
    var startY;
    var startLeft;
    var startTop;

    function move(event) {
      var maxLeft = Math.max(0, window.innerWidth - windowElement.offsetWidth);
      var maxTop = Math.max(46, window.innerHeight - windowElement.offsetHeight);
      windowElement.style.left = Math.min(maxLeft, Math.max(0, startLeft + event.clientX - startX)) + "px";
      windowElement.style.top = Math.min(maxTop, Math.max(46, startTop + event.clientY - startY)) + "px";
      windowElement.style.right = "auto";
      windowElement.style.bottom = "auto";
    }

    handle.addEventListener("pointerdown", function (event) {
      if (event.target.closest(".window-control") || windowElement.classList.contains("maximized")) return;
      bringToFront(windowElement);
      var rect = windowElement.getBoundingClientRect();
      startX = event.clientX;
      startY = event.clientY;
      startLeft = rect.left;
      startTop = rect.top;
      windowElement.style.left = startLeft + "px";
      windowElement.style.top = startTop + "px";
      windowElement.style.right = "auto";
      windowElement.style.bottom = "auto";
      handle.setPointerCapture(event.pointerId);
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", function () {
        handle.removeEventListener("pointermove", move);
      }, { once: true });
    });
  }

  function navigateBrowser() {
    var address = document.getElementById("browser-address");
    var value = address.value.trim();
    var message = document.getElementById("browser-message");
    var externalLink = document.getElementById("browser-external");
    if (!value) {
      message.textContent = "Enter a web address or search term.";
      return;
    }
    if (!/^https?:\/\//i.test(value)) {
      value = "https://www.google.com/search?q=" + encodeURIComponent(value);
    }
    address.value = value;
    externalLink.href = value;
    document.getElementById("browser-frame").src = value;
    message.textContent = "Loading in Walter. Use Open if this site blocks in-window display.";
  }

  function animateEyes(event) {
    document.querySelectorAll(".eye i").forEach(function (pupil) {
      var eye = pupil.parentElement.getBoundingClientRect();
      var x = event.clientX - (eye.left + eye.width / 2);
      var y = event.clientY - (eye.top + eye.height / 2);
      var distance = Math.max(1, Math.sqrt(x * x + y * y));
      var range = 17;
      pupil.style.transform = "translate(" + (x / distance * range) + "px, " + (y / distance * range) + "px)";
    });
  }

  function saveIdeFile() {
    var editor = document.getElementById("ide-code");
    ideFiles[ideActiveFile] = editor.value;
    localStorage.setItem("walter.ide." + ideActiveFile, editor.value);
    document.getElementById("ide-status").textContent = "Saved locally";
  }

  function selectIdeFile(fileName) {
    saveIdeFile();
    ideActiveFile = fileName;
    document.getElementById("ide-code").value = ideFiles[fileName];
    document.querySelectorAll("[data-ide-tab]").forEach(function (tab) {
      var selected = tab.dataset.ideTab === fileName;
      tab.classList.toggle("active", selected);
      tab.setAttribute("aria-selected", String(selected));
    });
  }

  function runIde() {
    saveIdeFile();
    var safeScript = ideFiles.js.replace(/<\/script/gi, "<\\/script");
    document.getElementById("ide-frame").srcdoc = [
      "<!doctype html><html><head><meta charset=\"utf-8\"><style>",
      ideFiles.css,
      "</style></head><body>",
      ideFiles.html,
      "<script>",
      safeScript,
      "<\\/script></body></html>"
    ].join("");
    document.getElementById("ide-status").textContent = "Preview updated";
  }

  function resetIde() {
    ideFiles = { html: ideDefaults.html, css: ideDefaults.css, js: ideDefaults.js };
    Object.keys(ideFiles).forEach(function (fileName) {
      localStorage.setItem("walter.ide." + fileName, ideFiles[fileName]);
    });
    document.getElementById("ide-code").value = ideFiles[ideActiveFile];
    runIde();
  }

  function formatCalculator(value) {
    if (!Number.isFinite(value)) return "Error";
    return String(Number(value.toPrecision(12)));
  }

  function calculateResult() {
    if (calculator.stored === null || !calculator.operator) return;
    var current = Number(calculator.display);
    var result;
    if (calculator.operator === "add") result = calculator.stored + current;
    if (calculator.operator === "subtract") result = calculator.stored - current;
    if (calculator.operator === "multiply") result = calculator.stored * current;
    if (calculator.operator === "divide") result = current === 0 ? NaN : calculator.stored / current;
    calculator.display = formatCalculator(result);
    calculator.stored = null;
    calculator.operator = null;
    calculator.replace = true;
  }

  function updateCalculator(action) {
    if (/^\d$/.test(action)) {
      calculator.display = calculator.replace || calculator.display === "0" ? action : calculator.display + action;
      calculator.replace = false;
    } else if (action === "decimal" && !calculator.display.includes(".")) {
      calculator.display += ".";
      calculator.replace = false;
    } else if (action === "clear") {
      calculator = { display: "0", stored: null, operator: null, replace: false };
    } else if (action === "sign") {
      calculator.display = formatCalculator(-Number(calculator.display));
    } else if (action === "percent") {
      calculator.display = formatCalculator(Number(calculator.display) / 100);
      calculator.replace = true;
    } else if (action === "equals") {
      calculateResult();
    } else if (["add", "subtract", "multiply", "divide"].includes(action)) {
      if (calculator.operator && !calculator.replace) calculateResult();
      calculator.stored = Number(calculator.display);
      calculator.operator = action;
      calculator.replace = true;
    }
    document.getElementById("calculator-display").textContent = calculator.display;
  }

  function updateNotepad() {
    var heading = document.getElementById("notepad-heading");
    var body = document.getElementById("notepad-body");
    var words = body.value.trim() ? body.value.trim().split(/\s+/).length : 0;
    localStorage.setItem("walter.notepad.heading", heading.value);
    localStorage.setItem("walter.notepad.body", body.value);
    document.getElementById("notepad-status").textContent = "Saved locally";
    document.getElementById("notepad-count").textContent = words + (words === 1 ? " word" : " words");
  }

  function terminalLine(text, className) {
    var line = document.createElement("div");
    line.textContent = text;
    if (className) line.className = className;
    document.getElementById("terminal-output").appendChild(line);
  }

  function runTerminalCommand(rawCommand) {
    var command = rawCommand.trim();
    var parts = command.split(/\s+/);
    var name = parts[0].toLowerCase();
    var args = parts.slice(1);
    terminalLine("visitor@walter:~$ " + command);
    if (!command) return;
    if (name === "help") terminalLine("Commands: help, clear, date, echo, whoami, pwd, ls, cat, open, about");
    else if (name === "clear") document.getElementById("terminal-output").replaceChildren();
    else if (name === "date") terminalLine(new Date().toString());
    else if (name === "echo") terminalLine(args.join(" "));
    else if (name === "whoami") terminalLine("visitor");
    else if (name === "pwd") terminalLine("/home/visitor");
    else if (name === "ls") terminalLine("Desktop  Documents  Notes  welcome.txt");
    else if (name === "cat" && args.join(" ") === "welcome.txt") terminalLine("Welcome to Walter. This terminal is simulated and cannot access the host computer.");
    else if (name === "cat") terminalLine("cat: " + (args.join(" ") || "missing file operand") + ": No such file");
    else if (name === "about") terminalLine("Walter is a desktop inside a web page.");
    else if (name === "open" && args[0]) {
      var apps = { browser: "browser-window", files: "files-window", ide: "ide-window", clock: "clock-window", eyes: "eyes-window", calculator: "calculator-window", notepad: "notepad-window" };
      if (apps[args[0].toLowerCase()]) openWindow(apps[args[0].toLowerCase()]);
      else terminalLine("open: app not found. Try browser, files, ide, clock, eyes, calculator, or notepad.");
    } else if (name === "open") terminalLine("open: missing app name");
    else terminalLine(name + ": command not found. Type help for available commands.");
  }

  document.querySelectorAll("[data-open-window]").forEach(function (button) {
    button.addEventListener("click", function () { openWindow(button.dataset.openWindow); });
  });
  document.querySelectorAll("[data-window-action]").forEach(function (button) {
    button.addEventListener("click", function (event) {
      event.stopPropagation();
      var windowElement = button.closest("[data-window]");
      if (button.dataset.windowAction === "close") windowElement.hidden = true;
      if (button.dataset.windowAction === "minimize") windowElement.classList.add("minimized");
      if (button.dataset.windowAction === "maximize") windowElement.classList.toggle("maximized");
      updateDock();
    });
  });
  windows.forEach(function (windowElement) {
    windowElement.addEventListener("mousedown", function () { bringToFront(windowElement); });
    makeDraggable(windowElement);
  });
  document.getElementById("browser-form").addEventListener("submit", function (event) { event.preventDefault(); navigateBrowser(); });
  document.getElementById("browser-address").addEventListener("keydown", function (event) {
    if (event.key === "Enter") {
      event.preventDefault();
      navigateBrowser();
    }
  });
  document.getElementById("browser-go").addEventListener("click", navigateBrowser);
  document.getElementById("browser-back").addEventListener("click", function () {
    document.getElementById("browser-frame").contentWindow.history.back();
  });
  document.querySelector("[data-action='arrange']").addEventListener("click", arrangeWindows);
  document.getElementById("new-file").addEventListener("click", function () {
    var list = document.getElementById("file-list");
    var row = document.createElement("button");
    row.className = "file-row";
    row.innerHTML = '<span class="file-icon document">▤</span><span><strong>Untitled note.txt</strong><small>Created just now</small></span><span>···</span>';
    list.prepend(row);
  });
  document.getElementById("calculator-keys").addEventListener("click", function (event) {
    var button = event.target.closest("[data-calc]");
    if (button) updateCalculator(button.dataset.calc);
  });
  document.querySelectorAll("[data-ide-tab]").forEach(function (tab) {
    tab.addEventListener("click", function () { selectIdeFile(tab.dataset.ideTab); });
  });
  document.getElementById("ide-code").addEventListener("input", function () {
    document.getElementById("ide-status").textContent = "Saving…";
    saveIdeFile();
  });
  document.getElementById("ide-run").addEventListener("click", runIde);
  document.getElementById("ide-reset").addEventListener("click", resetIde);
  document.getElementById("ide-code").value = ideFiles[ideActiveFile];
  var notepadHeading = document.getElementById("notepad-heading");
  var notepadBody = document.getElementById("notepad-body");
  notepadHeading.value = localStorage.getItem("walter.notepad.heading") || notepadHeading.value;
  notepadBody.value = localStorage.getItem("walter.notepad.body") || "";
  notepadHeading.addEventListener("input", updateNotepad);
  notepadBody.addEventListener("input", updateNotepad);
  updateNotepad();
  document.getElementById("terminal-form").addEventListener("submit", function (event) {
    event.preventDefault();
    var input = document.getElementById("terminal-input");
    runTerminalCommand(input.value);
    input.value = "";
    document.getElementById("terminal-content").scrollTop = document.getElementById("terminal-content").scrollHeight;
  });
  document.querySelectorAll("[data-open-window='terminal-window']").forEach(function (button) {
    button.addEventListener("click", function () {
      window.setTimeout(function () { document.getElementById("terminal-input").focus(); }, 0);
    });
  });
  document.addEventListener("pointermove", animateEyes);
  updateClock();
  runIde();
  updateDock();
  window.setInterval(updateClock, 30000);
}());
