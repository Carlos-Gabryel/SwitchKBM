// Dispara um tick a cada 5 ms (200 Hz) fora da thread principal, que sofre throttling de timers.
let timer = null;
self.onmessage = (e) => {
  if (e.data === "start" && timer === null) timer = setInterval(() => self.postMessage(0), 5);
  else if (e.data === "stop" && timer !== null) { clearInterval(timer); timer = null; }
};
