/* Camera helpers: capture, barcode scanning and a small image signature. */
const TT = (() => {
  const csrf = () => document.querySelector('meta[name=csrf]').content;

  async function post(url, body) {
    const r = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf()},
      body: JSON.stringify(body),
      credentials: 'same-origin',
    });
    let data = {};
    try { data = await r.json(); } catch (e) {}
    if (!r.ok && !data.error) data.error = 'Request failed (' + r.status + ')';
    return data;
  }

  async function startCamera(video) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia)
      throw new Error('Camera is not available here. Use "Take photo" instead.');
    const stream = await navigator.mediaDevices.getUserMedia(
      {video: {facingMode: {ideal: 'environment'}}, audio: false});
    video.srcObject = stream;
    video.setAttribute('playsinline', '');
    await video.play();
    return stream;
  }

  function stopCamera(stream, video) {
    if (stream) stream.getTracks().forEach(t => t.stop());
    if (video) video.srcObject = null;
  }

  // Draw the current video frame (or an image) onto a canvas no wider than maxW.
  function frameToCanvas(src, maxW = 640) {
    const w = src.videoWidth || src.naturalWidth || src.width;
    const h = src.videoHeight || src.naturalHeight || src.height;
    const scale = Math.min(1, maxW / w);
    const c = document.createElement('canvas');
    c.width = Math.round(w * scale); c.height = Math.round(h * scale);
    c.getContext('2d').drawImage(src, 0, 0, c.width, c.height);
    return c;
  }

  function fileToCanvas(file, maxW = 640) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => { resolve(frameToCanvas(img, maxW)); URL.revokeObjectURL(img.src); };
      img.onerror = () => reject(new Error('Could not read that picture.'));
      img.src = URL.createObjectURL(file);
    });
  }

  const toBlob = c => new Promise(res => c.toBlob(res, 'image/jpeg', 0.85));

  function small(canvas, w, h) {
    // centre-crop 80% so the product, not the background, dominates
    const sx = canvas.width * 0.1, sy = canvas.height * 0.1;
    const c = document.createElement('canvas'); c.width = w; c.height = h;
    const x = c.getContext('2d', {willReadFrequently: true});
    x.drawImage(canvas, sx, sy, canvas.width * 0.8, canvas.height * 0.8, 0, 0, w, h);
    return x.getImageData(0, 0, w, h).data;
  }

  // 64-bit difference hash (shape) + 3x3 average colour grid (colour), as hex.
  function signature(canvas) {
    const d = small(canvas, 9, 8);
    const g = i => 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
    let bits = '';
    for (let y = 0; y < 8; y++)
      for (let x = 0; x < 8; x++)
        bits += g((y * 9 + x) * 4) > g((y * 9 + x + 1) * 4) ? '1' : '0';
    let hex = '';
    for (let i = 0; i < 64; i += 4) hex += parseInt(bits.slice(i, i + 4), 2).toString(16);
    const c = small(canvas, 3, 3);
    for (let i = 0; i < 9; i++)
      for (let k = 0; k < 3; k++) hex += c[i * 4 + k].toString(16).padStart(2, '0');
    return hex;
  }

  // Continuous barcode scanning on a playing <video>. Returns a stop() function.
  async function scanBarcodes(video, onCode) {
    let stopped = false, last = '', lastAt = 0;
    const emit = code => {
      const now = Date.now();
      if (code === last && now - lastAt < 2000) return;  // same label still in view
      last = code; lastAt = now; onCode(code);
    };
    if ('BarcodeDetector' in window) {
      const det = new BarcodeDetector({formats: ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39', 'itf', 'qr_code']});
      (async function loop() {
        while (!stopped) {
          try {
            const found = await det.detect(video);
            if (found.length) emit(found[0].rawValue);
          } catch (e) {}
          await new Promise(r => setTimeout(r, 200));
        }
      })();
      return () => { stopped = true; };
    }
    await new Promise((res, rej) => {
      if (window.ZXing) return res();
      const s = document.createElement('script');
      s.src = 'https://cdn.jsdelivr.net/npm/@zxing/library@0.21.3/umd/index.min.js';
      s.onload = res; s.onerror = () => rej(new Error('Barcode scanning is not supported in this browser. Type the number instead.'));
      document.head.appendChild(s);
    });
    const reader = new ZXing.BrowserMultiFormatReader();
    reader.decodeFromVideoElement(video, (result) => { if (result && !stopped) emit(result.getText()); });
    return () => { stopped = true; try { reader.reset(); } catch (e) {} };
  }

  return {post, startCamera, stopCamera, frameToCanvas, fileToCanvas, toBlob, signature, scanBarcodes, csrf};
})();
