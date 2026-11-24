// Regierungsfahrzeuge in 3D (regierung.py, /regierung/fahrzeuge/<ministerium>/).
// Eigene, prozedural gebaute Modelle (keine fremden Modelldateien), damit jede Behörde ihre eigene Lackierung bekommt:
// Rumpf als Ringe mit UV (u = Länge, v = Umfang) → Lackierung wird auf eine Leinwand gemalt (Titel, Zierlinie, Fenster, Kennung),
// Leitwerk mit Reichsadler, Limousinen in Wagenfarbe mit Standarten und Kennzeichen.
// Daten kommen aus <script type="application/json" id="fz-daten">: {typ, art, kennung, name, behoerde, akzent, sonder, adler}
import * as THREE from "three";
import { OrbitControls } from "./OrbitControls.js";
import { RoomEnvironment } from "./RoomEnvironment.js";
import { GLTFLoader } from "./loaders/GLTFLoader.js";
import { MeshoptDecoder } from "./libs/meshopt_decoder.module.js";
import { DecalGeometry } from "./geometries/DecalGeometry.js";

const D = JSON.parse(document.getElementById("fz-daten").textContent);
const huelle = document.getElementById("fz-buehne");
const W = () => huelle.clientWidth, H = () => huelle.clientHeight;

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(W(), H());
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
renderer.outputColorSpace = THREE.SRGBColorSpace;
huelle.appendChild(renderer.domElement);

const szene = new THREE.Scene();
const pmrem = new THREE.PMREMGenerator(renderer);
szene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
const kamera = new THREE.PerspectiveCamera(32, W() / H(), 0.1, 1000);
const steuerung = new OrbitControls(kamera, renderer.domElement);
steuerung.enableDamping = true;
steuerung.autoRotate = !matchMedia("(prefers-reduced-motion: reduce)").matches;
steuerung.autoRotateSpeed = 0.9;
const sonne = new THREE.DirectionalLight(0xffffff, 1.6);
sonne.position.set(-6, 10, 8);
szene.add(sonne, new THREE.HemisphereLight(0xffffff, 0x9aa3b0, 0.6));

// ------------------------------------------------------------ Farben und Hilfen
const AKZENT = new THREE.Color(D.akzent || "#1f2f45");
const GOLD = "#d4a72c", SCHWARZ = "#111317";
const lack = (farbe, glanz = 0.35) => new THREE.MeshPhysicalMaterial({ color: farbe, metalness: 0.15, roughness: glanz, clearcoat: 0.6, clearcoatRoughness: 0.12 });
const matt = (farbe, r = 0.6, m = 0.2) => new THREE.MeshStandardMaterial({ color: farbe, roughness: r, metalness: m });
const glas = new THREE.MeshPhysicalMaterial({ color: 0x0d1117, roughness: 0.05, metalness: 0.1, clearcoat: 1, transparent: true, opacity: 0.92 });
const chrom = new THREE.MeshStandardMaterial({ color: 0xdfe3e8, roughness: 0.15, metalness: 1 });

function leinwand(b, h) { const c = document.createElement("canvas"); c.width = b; c.height = h; return [c, c.getContext("2d")]; }
function textur(c) { const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8; t.flipY = false; return t; }

const adlerBild = new Image();
const adlerGeladen = new Promise(ok => { adlerBild.onload = ok; adlerBild.onerror = ok; });
adlerBild.src = D.adler;

// Reichsadler einfarbig (Gold/Weiß) aus dem Logo: linker Teil des Kurzlogos (rechts davon steht der Balken)
function adler(ctx, x, y, h, farbe) {
  if (!adlerBild.naturalWidth) return;
  const sw = adlerBild.naturalWidth * 0.74, sh = adlerBild.naturalHeight, w = h * sw / sh;
  const [c, g] = leinwand(Math.ceil(w), Math.ceil(h));
  g.drawImage(adlerBild, 0, 0, sw, sh, 0, 0, w, h);
  g.globalCompositeOperation = "source-in"; g.fillStyle = farbe; g.fillRect(0, 0, w, h);
  ctx.drawImage(c, x - w / 2, y - h / 2);
}
function schrift(ctx, text, x, y, groesse, farbe, gewicht = 700, abstand = 0.12) {
  ctx.save(); ctx.fillStyle = farbe; ctx.font = `${gewicht} ${groesse}px "Segoe UI", Roboto, Arial, sans-serif`;
  ctx.textBaseline = "middle"; ctx.letterSpacing = `${groesse * abstand}px`; ctx.fillText(text, x, y); ctx.restore();
}

// ------------------------------------------------------------ Rumpf: Ringe entlang x (Nase bei x = 0, zeigt nach -x)
// r(t), y-Mitte(t) mit t = 0..1; UV: u = t, v = Winkel/2π (0 oben, 0.25 rechts (+z), 0.5 unten, 0.75 links)
function rumpf({ laenge, radius, nase = 0.11, heck = 0.24, heckR = 0.14, heckHoch = 0.55, oval = 1.0 }, material) {
  const N = 140, M = 64, pos = [], uv = [], idx = [];
  const r = t => t < nase ? radius * Math.sqrt(Math.max(0, 1 - Math.pow(1 - t / nase, 2.2))) :
    t > 1 - heck ? radius * (heckR + (1 - heckR) * Math.pow((1 - t) / heck, 0.85)) : radius;
  const cy = t => t > 1 - heck ? radius * heckHoch * Math.pow((t - (1 - heck)) / heck, 1.6) : (t < nase ? -radius * 0.12 * Math.pow(1 - t / nase, 2) : 0);
  for (let i = 0; i <= N; i++) {
    const t = i / N, rr = Math.max(r(t), 0.0005), y0 = cy(t);
    for (let j = 0; j <= M; j++) {
      const a = (j / M) * Math.PI * 2;
      pos.push(t * laenge, y0 + rr * Math.cos(a) * oval, rr * Math.sin(a));
      uv.push(t, j / M);
    }
  }
  for (let i = 0; i < N; i++) for (let j = 0; j < M; j++) {
    const a = i * (M + 1) + j, b = a + M + 1;
    idx.push(a, a + 1, b, b, a + 1, b + 1);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
  g.setIndex(idx); g.computeVertexNormals();
  return new THREE.Mesh(g, material);
}

// Tragfläche/Höhenleitwerk: Grundriss in x/z, als dünnes Profil extrudiert (y), Pfeilung, V-Stellung, Spitze
function flaeche({ wurzel, spitze, spann, pfeil, dicke, vform = 0 }, material, seite) {
  const s = new THREE.Shape(), sp = spann * seite;
  s.moveTo(0, 0); s.lineTo(pfeil, sp); s.lineTo(pfeil + spitze, sp); s.lineTo(wurzel, 0); s.closePath();
  const g = new THREE.ExtrudeGeometry(s, { depth: dicke, bevelEnabled: true, bevelThickness: dicke * 0.45, bevelSize: dicke * 0.45, bevelSegments: 3, steps: 1 });
  g.rotateX(Math.PI / 2);           // Grundriss in x/z (Spannweite → +z bzw. -z)
  g.translate(0, dicke / 2, 0);
  const m = new THREE.Mesh(g, material);
  m.rotation.x = -seite * vform;
  return m;
}

// Seitenleitwerk als Fläche in x/y mit eigener Lackierung (Akzentfarbe, Goldband, Reichsadler)
function seitenleitwerk({ wurzel, spitze, hoehe, pfeil, dicke }) {
  const s = new THREE.Shape();
  s.moveTo(0, 0); s.lineTo(pfeil, hoehe); s.lineTo(pfeil + spitze, hoehe); s.lineTo(wurzel, 0); s.closePath();
  const g = new THREE.ExtrudeGeometry(s, { depth: dicke, bevelEnabled: true, bevelThickness: dicke * 0.4, bevelSize: dicke * 0.4, bevelSegments: 2 });
  g.translate(0, 0, -dicke / 2);
  const [c, ctx] = leinwand(1024, 1024);
  ctx.fillStyle = "#" + AKZENT.getHexString(); ctx.fillRect(0, 0, 1024, 1024);
  ctx.fillStyle = GOLD; ctx.fillRect(0, 300, 1024, 40);
  ctx.fillStyle = SCHWARZ; ctx.fillRect(0, 340, 1024, 26);
  adler(ctx, 560, 620, 360, "#ffffff");
  // UV der Extrusion = Shape-Koordinaten → auf die Leinwand abbilden (Leinwand y nach unten, Leitwerk y nach oben)
  const breite = pfeil + spitze + 0.2, t = textur(c);
  t.flipY = true;
  t.repeat.set(1 / breite, 1 / hoehe); t.offset.set(0, 0);
  const m = new THREE.Mesh(g, [new THREE.MeshPhysicalMaterial({ map: t, roughness: 0.32, clearcoat: 0.6 }), lack(AKZENT)]);
  return m;
}

function triebwerk(laenge, radius, material) {
  const p = [];
  const n = 24;
  for (let i = 0; i <= n; i++) {
    const t = i / n;
    const r = t < 0.12 ? radius * (0.86 + 0.14 * Math.sin(t / 0.12 * Math.PI / 2)) : radius * (1 - 0.32 * Math.pow((t - 0.12) / 0.88, 1.8));
    p.push(new THREE.Vector2(r, t * laenge));
  }
  const g = new THREE.LatheGeometry(p, 40);
  g.rotateZ(Math.PI / 2); g.rotateY(Math.PI);   // Achse entlang +x, Einlass vorne (-x)
  const gr = new THREE.Group();
  material.side = THREE.DoubleSide;
  const huelle = new THREE.Mesh(g, material);
  const einlass = new THREE.Mesh(new THREE.CircleGeometry(radius * 0.84, 40), matt(0x22262c, 0.5, 0.6));
  einlass.rotation.y = -Math.PI / 2; einlass.position.x = 0.02;
  const fan = new THREE.Mesh(new THREE.CylinderGeometry(radius * 0.22, radius * 0.22, 0.05, 20), chrom);
  fan.rotation.z = Math.PI / 2; fan.position.x = 0.08;
  gr.add(huelle, einlass, fan);
  return gr;
}

// ------------------------------------------------------------ Lackierung des Rumpfs (u entlang, v rundherum)
function rumpfLackierung(laenge, umfang, { fensterVon = 0.17, fensterBis = 0.86, fensterZahl = 40, tueren = [0.15, 0.48, 0.83], titel = true, titelU = 0.2, cockpit = 1 }) {
  const B = 4096, Hh = 1024, [c, ctx] = leinwand(B, Hh);
  const v = x => x * Hh, u = x => x * B;
  ctx.fillStyle = "#f6f7f9"; ctx.fillRect(0, 0, B, Hh);
  // Bauch in Akzentfarbe, Zierlinie Schwarz-Gold auf beiden Seiten
  ctx.fillStyle = "#" + AKZENT.getHexString(); ctx.fillRect(0, v(0.355), B, v(0.29));
  for (const [a, b, f] of [[0.335, 0.348, GOLD], [0.322, 0.335, SCHWARZ], [0.652, 0.665, GOLD], [0.665, 0.678, SCHWARZ]]) { ctx.fillStyle = f; ctx.fillRect(0, v(a), B, v(b - a)); }
  // Fensterreihe (rechts bei v≈0.215, links gespiegelt bei v≈0.785), Türen, Cockpit
  const fh = Hh * 0.024, fw = fh * (laenge / umfang) * 0.55 * (B / Hh) / 4;
  for (const vy of [0.212, 0.788]) {
    for (let i = 0; i < fensterZahl; i++) {
      const x = u(fensterVon + (fensterBis - fensterVon) * i / (fensterZahl - 1));
      if (tueren.some(t => Math.abs(fensterVon + (fensterBis - fensterVon) * i / (fensterZahl - 1) - t) < 0.018)) continue;
      ctx.fillStyle = "#1b2430"; ctx.beginPath(); ctx.roundRect(x - fw / 2, v(vy) - fh / 2, fw, fh, fh * 0.4); ctx.fill();
    }
    for (const t of tueren) { ctx.strokeStyle = "#9aa3ae"; ctx.lineWidth = 3; ctx.beginPath(); ctx.roundRect(u(t) - fw * 1.3, v(vy) - fh * 1.9, fw * 2.6, fh * 4.3, 10); ctx.stroke(); }
  }
  ctx.fillStyle = "#151b24";
  for (const [vy, s] of [[0.135, 1], [0.865, -1]]) {
    const k = cockpit;
    ctx.beginPath(); ctx.moveTo(u(0.035 * k), v(vy) - s * 6 * k); ctx.lineTo(u(0.062 * k), v(vy) - s * 14 * k); ctx.lineTo(u(0.066 * k), v(vy) + s * 26 * k); ctx.lineTo(u(0.038 * k), v(vy) + s * 22 * k); ctx.closePath(); ctx.fill();
  }
  // Titel: rechts normal, links um 180° gedreht (dort läuft u/v gespiegelt)
  if (titel) {
    const zeile = (vy, dreh) => {
      ctx.save();
      // linke Seite: u läuft dort von rechts nach links und v von unten nach oben → um 180° drehen; X() spiegelt die Zielposition
      if (dreh) { ctx.translate(B, v(vy) * 2); ctx.scale(-1, -1); ctx.textAlign = "right"; }
      const X = x => dreh ? B - x : x;
      const y = v(vy), gr = Hh * 0.05, ak = "#" + AKZENT.getHexString();
      schrift(ctx, "IMPERIUM GERMANICUM", X(u(titelU)), y, gr, "#1a2230", 700, 0.22);
      schrift(ctx, (D.behoerde || "").toUpperCase(), X(u(titelU)), y + gr * 1.25, gr * 0.42, ak, 600, 0.18);
      adler(ctx, X(u(titelU - 0.06)), y + gr * 0.3, gr * 1.8, ak);
      schrift(ctx, D.kennung || "", X(u(0.74)), y + Hh * 0.07, gr * 0.6, "#3a4250", 700, 0.1);
      if (D.name) schrift(ctx, D.name, X(u(0.07)), y + Hh * 0.05, gr * 0.42, "#3a4250", 500, 0.04);
      ctx.restore();
    };
    zeile(0.15, false); zeile(0.85, true);
  }
  return textur(c);
}

// ------------------------------------------------------------ Flugzeuge
const FLUGZEUGE = {
  a350: { laenge: 66.8, radius: 2.98, spann: 64.75, wurzel: 13, spitze: 2.2, pfeil: 13.5, wflaeche: 0.36, triebwerk: [6.5, 1.55, 0.31], winglet: "gebogen", fenster: 46, leitwerk: 9.2 },
  a330: { laenge: 58.8, radius: 2.82, spann: 60.3, wurzel: 11.5, spitze: 2.3, pfeil: 12.5, wflaeche: 0.37, triebwerk: [5.6, 1.4, 0.32], winglet: "steil", fenster: 42, leitwerk: 8.6 },
  a321: { laenge: 44.5, radius: 2.0, spann: 35.8, wurzel: 7.2, spitze: 1.6, pfeil: 6.2, wflaeche: 0.38, triebwerk: [4.6, 1.05, 0.31], winglet: "sharklet", fenster: 34, leitwerk: 6.2 },
  a319: { laenge: 33.8, radius: 2.0, spann: 35.8, wurzel: 7.2, spitze: 1.6, pfeil: 6.2, wflaeche: 0.39, triebwerk: [4.6, 1.05, 0.31], winglet: "sharklet", fenster: 24, leitwerk: 6.2 },
  global: { laenge: 30.3, radius: 1.35, spann: 28.6, wurzel: 5.4, spitze: 1.2, pfeil: 5.6, wflaeche: 0.47, triebwerk: [4.0, 0.72, 0], heckTriebwerk: true, winglet: "steil", fenster: 7, leitwerk: 4.6, tLeitwerk: true },
};

function flugzeug(p) {
  const gr = new THREE.Group();
  const umfang = 2 * Math.PI * p.radius;
  const tueren = p.fenster < 10 ? [0.16] : p.laenge > 50 ? [0.14, 0.42, 0.78] : [0.15, 0.52, 0.84];
  const map = rumpfLackierung(p.laenge, umfang, { fensterZahl: p.fenster, fensterVon: p.fenster < 10 ? 0.24 : 0.16, fensterBis: p.fenster < 10 ? 0.5 : 0.86, tueren });
  const hautMat = new THREE.MeshPhysicalMaterial({ map, roughness: 0.28, metalness: 0.05, clearcoat: 0.8, clearcoatRoughness: 0.1 });
  const r = rumpf({ laenge: p.laenge, radius: p.radius, heck: p.heckTriebwerk ? 0.27 : 0.24 }, hautMat);
  gr.add(r);
  const fl = matt(0xd9dde3, 0.45, 0.35);
  const wx = p.laenge * p.wflaeche, hs = p.spann / 2 - p.radius * 0.8;
  for (const s of [1, -1]) {
    const w = flaeche({ wurzel: p.wurzel, spitze: p.spitze, spann: hs, pfeil: p.pfeil, dicke: p.radius * 0.11, vform: 0.085 }, fl, s);
    w.position.set(wx, -p.radius * 0.55, s * p.radius * 0.8); gr.add(w);
    // Winglet
    const wl = new THREE.Shape(), hh = p.winglet === "sharklet" ? 2.4 : p.winglet === "gebogen" ? 3.6 : 2.8;
    wl.moveTo(0, 0); wl.lineTo(p.spitze * 0.55, hh); wl.lineTo(p.spitze * 0.95, hh); wl.lineTo(p.spitze, 0); wl.closePath();
    const wg = new THREE.Mesh(new THREE.ExtrudeGeometry(wl, { depth: 0.08, bevelEnabled: false }), lack(AKZENT));
    const tipY = -p.radius * 0.55 + Math.sin(0.085) * hs, tipZ = s * (p.radius * 0.8 + Math.cos(0.085) * hs);
    wg.position.set(wx + p.pfeil, tipY, tipZ); wg.rotation.x = s * -0.18; gr.add(wg);
    // Triebwerke unter der Fläche bzw. am Heck
    if (!p.heckTriebwerk) {
      const [tl, tr, pos] = p.triebwerk;
      const tw = triebwerk(tl, tr, lack(0xf1f2f4, 0.3));
      const zz = s * (p.radius * 0.8 + hs * pos);
      tw.position.set(wx + p.pfeil * pos - tl * 0.62, -p.radius * 0.55 + Math.sin(0.085) * hs * pos - tr * 1.25, zz);
      const pylon = new THREE.Mesh(new THREE.BoxGeometry(tl * 0.7, tr * 0.9, 0.22), fl);
      pylon.position.set(tw.position.x + tl * 0.55, tw.position.y + tr * 0.95, zz);
      gr.add(tw, pylon);
    }
  }
  if (p.heckTriebwerk) {
    const [tl, tr] = p.triebwerk;
    for (const s of [1, -1]) {
      const tw = triebwerk(tl, tr, lack(0xf1f2f4, 0.3));
      tw.position.set(p.laenge * 0.68, p.radius * 0.35, s * (p.radius + tr * 1.15));
      const pylon = new THREE.Mesh(new THREE.BoxGeometry(tl * 0.5, 0.25, tr * 1.3), fl);
      pylon.position.set(tw.position.x + tl * 0.5, tw.position.y, s * (p.radius + tr * 0.35));
      gr.add(tw, pylon);
    }
  }
  // Leitwerk
  const lh = p.leitwerk, fin = seitenleitwerk({ wurzel: lh * 1.05, spitze: lh * 0.42, hoehe: lh, pfeil: lh * 0.75, dicke: p.radius * 0.09 });
  fin.position.set(p.laenge * 0.8, p.radius * 0.5, 0); gr.add(fin);
  const hl = p.leitwerk * 0.85;
  for (const s of [1, -1]) {
    const h = flaeche({ wurzel: hl * 0.75, spitze: hl * 0.3, spann: hl * 1.15, pfeil: hl * 0.55, dicke: p.radius * 0.06, vform: p.tLeitwerk ? 0 : 0.1 }, fl, s);
    if (p.tLeitwerk) h.position.set(p.laenge * 0.8 + lh * 0.75 + lh * 0.05, p.radius * 0.5 + lh - p.radius * 0.04, 0);
    else h.position.set(p.laenge * 0.85, p.radius * 0.28, s * p.radius * 0.2);
    gr.add(h);
  }
  gr.position.x = -p.laenge * 0.5;
  return { modell: gr, groesse: Math.max(p.laenge, p.spann) };
}

// ------------------------------------------------------------ Hubschrauber (Airbus H225M)
let rotor = null, heckrotor = null;
function hubschrauber() {
  const gr = new THREE.Group();
  const laenge = 16.8, radius = 1.45;
  const map = rumpfLackierung(laenge, 2 * Math.PI * radius, { fensterZahl: 4, fensterVon: 0.2, fensterBis: 0.34, tueren: [0.27], titel: true, titelU: 0.43, cockpit: 2.3 });
  const haut = new THREE.MeshPhysicalMaterial({ map, roughness: 0.3, clearcoat: 0.7 });
  const r = rumpf({ laenge, radius, nase: 0.16, heck: 0.6, heckR: 0.1, heckHoch: 0.62, oval: 1.12 }, haut);
  gr.add(r);
  const fin = seitenleitwerk({ wurzel: 1.6, spitze: 0.9, hoehe: 2.2, pfeil: 0.9, dicke: 0.16 });
  fin.position.set(laenge - 1.7, radius * 0.75, 0); gr.add(fin);
  const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.32, 1.1, 16), matt(0x30353c, 0.4, 0.7));
  mast.position.set(6.4, radius + 0.9, 0); gr.add(mast);
  const verkleidung = new THREE.Mesh(new THREE.SphereGeometry(1, 32, 16), lack(0xf4f5f7, 0.3));
  verkleidung.scale.set(3.0, 0.55, 0.95); verkleidung.position.set(6.7, radius + 0.42, 0); gr.add(verkleidung);
  const band = new THREE.Mesh(new THREE.TorusGeometry(1, 0.04, 8, 48), lack(AKZENT)); band.scale.set(3.0, 0.95, 1); band.rotation.x = Math.PI / 2; band.position.set(6.7, radius + 0.25, 0); gr.add(band);
  rotor = new THREE.Group(); rotor.position.set(6.4, radius + 1.45, 0);
  for (let i = 0; i < 5; i++) {
    const b = new THREE.Mesh(new THREE.BoxGeometry(7.6, 0.05, 0.42), matt(0x1c1f24, 0.5, 0.3));
    b.position.x = 3.8; const h = new THREE.Group(); h.rotation.y = i * Math.PI * 2 / 5; h.add(b); rotor.add(h);
  }
  gr.add(rotor);
  heckrotor = new THREE.Group(); heckrotor.position.set(laenge - 0.6, radius * 0.75 + 1.4, 0.35);
  for (let i = 0; i < 4; i++) { const b = new THREE.Mesh(new THREE.BoxGeometry(0.18, 1.5, 0.05), matt(0x1c1f24)); b.position.y = 0.75; const h = new THREE.Group(); h.rotation.z = i * Math.PI / 2; h.add(b); heckrotor.add(h); }
  gr.add(heckrotor);
  for (const s of [1, -1]) {   // Kufen-Ersatz: Fahrwerksstummel mit Rädern
    const st = new THREE.Mesh(new THREE.CapsuleGeometry(0.32, 1.4, 6, 16), lack(AKZENT)); st.rotation.z = Math.PI / 2; st.position.set(7.0, -radius * 0.55, s * (radius * 0.98)); gr.add(st);
    const rd = new THREE.Mesh(new THREE.TorusGeometry(0.26, 0.11, 12, 24), matt(0x111214, 0.85, 0)); rd.position.set(7.0, -radius * 0.95, s * (radius * 0.98)); gr.add(rd);
  }
  gr.position.x = -laenge * 0.45;
  return { modell: gr, groesse: 17 };
}

// ------------------------------------------------------------ Limousinen und Transporter
// Seitenprofil (x vorne→hinten, y Höhe) wird über die Breite extrudiert; Glashaus eigenes, schmaleres Teil
const WAGEN = {
  sklasse: { laenge: 5.47, breite: 1.95, hoehe: 1.51, rad: 0.38, radstand: 3.4, dach: [0.30, 0.74], motorhaube: 0.92, heck: 0.95, glasHoch: 0.48, standarte: true },
  a8: { laenge: 5.45, breite: 1.95, hoehe: 1.49, rad: 0.38, radstand: 3.3, dach: [0.31, 0.76], motorhaube: 0.9, heck: 0.97, glasHoch: 0.46, standarte: true },
  bmw7: { laenge: 5.39, breite: 1.95, hoehe: 1.54, rad: 0.38, radstand: 3.2, dach: [0.30, 0.73], motorhaube: 0.95, heck: 0.98, glasHoch: 0.47, standarte: true },
  vklasse: { laenge: 5.14, breite: 1.93, hoehe: 1.88, rad: 0.36, radstand: 3.2, dach: [0.2, 0.97], motorhaube: 1.0, heck: 1.6, glasHoch: 0.6, van: true },
  sprinter: { laenge: 5.93, breite: 2.02, hoehe: 2.6, rad: 0.38, radstand: 3.67, dach: [0.17, 0.99], motorhaube: 1.05, heck: 2.45, glasHoch: 0.6, van: true },
};

function wagen(p) {
  const gr = new THREE.Group();
  const S = D.sonder;   // Polizei, Zoll, Katastrophenschutz → Behördenlackierung
  const grund = S ? (S.grund || "#eef0f3") : (D.farbe || "#0c0f14");
  const L = p.laenge, Hh = p.hoehe, R = p.rad, unten = 0.18, gurt = p.van ? Hh * 0.55 : Hh * 0.62;
  // Karosserie (bis Gurtlinie) mit Motorhaube/Heck
  const k = new THREE.Shape();
  k.moveTo(0, unten + 0.12); k.quadraticCurveTo(0, unten, 0.25, unten);
  const ra = L * 0.18 + 0.0, rb = ra + p.radstand;
  const radbogen = x => { k.lineTo(x - R * 1.15, unten); k.absarc(x, unten + 0.05, R * 1.12, Math.PI, 0, true); };
  radbogen(ra); radbogen(rb);
  k.lineTo(L - 0.2, unten); k.quadraticCurveTo(L, unten, L, unten + 0.2);
  k.lineTo(L, gurt - 0.08); k.quadraticCurveTo(L - 0.04, gurt, L - p.heck * 0.25, gurt + 0.02);
  k.lineTo(p.motorhaube * 0.35, gurt - 0.02); k.quadraticCurveTo(0.02, gurt - 0.1, 0, unten + 0.45); k.closePath();
  const kg = new THREE.ExtrudeGeometry(k, { depth: p.breite - 0.16, bevelEnabled: true, bevelThickness: 0.08, bevelSize: 0.07, bevelSegments: 5, curveSegments: 18 });
  kg.translate(0, 0, -(p.breite - 0.16) / 2);
  const karosse = new THREE.Mesh(kg, lack(grund, 0.22)); gr.add(karosse);
  // Glashaus (Dach in Wagenfarbe, Scheiben dunkel): Profil von A- bis C-Säule
  const [d0, d1] = p.dach, dachH = Hh;
  const g = new THREE.Shape();
  if (p.van) {
    g.moveTo(L * 0.06, gurt); g.lineTo(L * d0, dachH - 0.04); g.lineTo(L * d1, dachH - 0.02); g.lineTo(L - 0.03, gurt); g.closePath();
  } else {
    g.moveTo(p.motorhaube + 0.05, gurt); g.quadraticCurveTo(L * d0, dachH - 0.02, L * (d0 + 0.08), dachH);
    g.lineTo(L * (d1 - 0.06), dachH); g.quadraticCurveTo(L * d1, dachH - 0.03, L - p.heck * 0.75, gurt); g.closePath();
  }
  const gb = p.breite - 0.36;
  const gg = new THREE.ExtrudeGeometry(g, { depth: gb, bevelEnabled: true, bevelThickness: 0.07, bevelSize: 0.06, bevelSegments: 4, curveSegments: 16 });
  gg.translate(0, 0, -gb / 2);
  gr.add(new THREE.Mesh(gg, glas));
  const dach = new THREE.Mesh(new THREE.BoxGeometry(L * (d1 - d0) * (p.van ? 0.98 : 0.8), 0.06, gb + 0.1), lack(grund, 0.22));
  dach.position.set(L * (d0 + d1) / 2, dachH + 0.04, 0); gr.add(dach);
  // B- und C-Säulen in Wagenfarbe (Fensterteilung)
  for (const x of p.van ? [0.36, 0.58, 0.8] : [0.47, 0.62]) {
    const s = new THREE.Mesh(new THREE.BoxGeometry(0.09, dachH - gurt, gb + 0.16), lack(grund, 0.22)); s.position.set(L * x, (dachH + gurt) / 2, 0); gr.add(s);
  }
  // Räder
  const reifen = matt(0x111214, 0.85, 0), felge = chrom;
  for (const x of [ra, rb]) for (const s of [1, -1]) {
    const rad = new THREE.Group();
    const t = new THREE.Mesh(new THREE.TorusGeometry(R * 0.78, R * 0.24, 16, 40), reifen);
    const f = new THREE.Mesh(new THREE.CylinderGeometry(R * 0.62, R * 0.62, 0.22, 28), felge); f.rotation.x = Math.PI / 2;
    rad.add(t, f);
    for (let i = 0; i < 6; i++) { const sp = new THREE.Mesh(new THREE.BoxGeometry(R * 1.1, 0.06, 0.05), matt(0x2a2d33, 0.3, 0.9)); sp.rotation.z = i * Math.PI / 3; sp.position.z = s * 0.12; rad.add(sp); } rad.position.set(x, unten + 0.05, s * (p.breite / 2 - 0.12)); gr.add(rad);
  }
  // Lichter, Kühlergrill, Kennzeichen
  for (const s of [1, -1]) {
    const sw = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.1, 0.42), new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xe8f0ff, emissiveIntensity: 0.9 }));
    sw.position.set(0.02, gurt - 0.22, s * (p.breite / 2 - 0.35)); gr.add(sw);
    const rl = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.1, 0.5), new THREE.MeshStandardMaterial({ color: 0x8a0f12, emissive: 0x7a0000, emissiveIntensity: 0.6 }));
    rl.position.set(L + 0.02, gurt - 0.2, s * (p.breite / 2 - 0.32)); gr.add(rl);
  }
  const grill = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.32, 0.72), matt(0x15171a, 0.25, 0.9)); grill.position.set(-0.03, unten + 0.42, 0); gr.add(grill);
  const [kc, kx] = leinwand(520, 110);
  kx.fillStyle = "#fbfbf7"; kx.fillRect(0, 0, 520, 110); kx.strokeStyle = "#111"; kx.lineWidth = 6; kx.strokeRect(3, 3, 514, 104);
  kx.fillStyle = "#1f3a8a"; kx.fillRect(3, 3, 56, 104); schrift(kx, "IG", 10, 72, 26, "#fff", 700, 0);
  schrift(kx, D.kennung || "IG-R 1", 78, 57, 62, "#111", 700, 0.04);
  const kt = textur(kc); kt.flipY = true;
  for (const [x, ry] of [[-0.06, -Math.PI / 2], [L + 0.06, Math.PI / 2]]) {
    const sch = new THREE.Mesh(new THREE.PlaneGeometry(0.52, 0.11), new THREE.MeshStandardMaterial({ map: kt, roughness: 0.4 }));
    sch.rotation.y = ry; sch.position.set(x, unten + 0.22, 0); gr.add(sch);
  }
  // Behördenlackierung (Seitenstreifen + Schriftzug) als Abziehbilder je Seite
  if (S) {
    const [sc, sx] = leinwand(2048, 256);
    sx.fillStyle = S.streifen; sx.fillRect(0, 60, 2048, 120); sx.fillStyle = S.zweit || S.streifen; sx.fillRect(0, 180, 2048, 26);
    schrift(sx, S.text, 760, 122, 92, S.schrift || "#ffffff", 800, 0.12);
    const st = textur(sc); st.flipY = true;
    for (const s of [1, -1]) {
      const pl = new THREE.Mesh(new THREE.PlaneGeometry(L * 0.94, 0.42), new THREE.MeshStandardMaterial({ map: st, transparent: true, roughness: 0.3 }));
      pl.position.set(L / 2, gurt - 0.3, s * (p.breite / 2 + 0.012)); if (s < 0) pl.rotation.y = Math.PI; gr.add(pl);
    }
    const blau = new THREE.Mesh(new THREE.BoxGeometry(0.28, 0.1, 1.1), new THREE.MeshStandardMaterial({ color: S.licht || 0x1e5bff, emissive: S.licht || 0x1e5bff, emissiveIntensity: 1.2 }));
    blau.position.set(L * (d0 + 0.12), dachH + 0.12, 0); gr.add(blau);
  }
  // Standarten auf den Kotflügeln (Limousinen ohne Behördenlackierung)
  if (p.standarte && !S) {
    const [fc, fx] = leinwand(256, 160);
    fx.fillStyle = GOLD; fx.fillRect(0, 0, 256, 160); fx.fillStyle = SCHWARZ; fx.fillRect(0, 0, 256, 18); fx.fillRect(0, 142, 256, 18);
    adler(fx, 128, 80, 120, SCHWARZ);
    const ft = textur(fc); ft.flipY = true;
    for (const s of [1, -1]) {
      const stab = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, 0.32, 8), chrom); stab.position.set(0.28, gurt + 0.16, s * (p.breite / 2 - 0.25));
      const fahne = new THREE.Mesh(new THREE.PlaneGeometry(0.26, 0.16), new THREE.MeshStandardMaterial({ map: ft, side: THREE.DoubleSide, roughness: 0.8 }));
      fahne.position.set(0.42, gurt + 0.25, s * (p.breite / 2 - 0.25)); gr.add(stab, fahne);
    }
  }
  gr.position.set(-L / 2, -0.1, 0);
  return { modell: gr, groesse: L * 1.25, boden: true };
}


// ============================================================ Echte Modelle (Sketchfab, CC BY 4.0; Nachweis auf der Seite)
// achse: Längsachse im Modell; nase: +1/-1 = Nase zeigt in +/- Richtung dieser Achse; laenge: echte Länge in m.
// Nach dem Ausrichten zeigt die Nase immer nach -x (wie bei den eigenen Modellen), Mitte im Ursprung.
const MODELLE = {
  a350: { achse: "z", nase: 1, laenge: 66.8, art: "flug" },
  a330: { achse: "z", nase: 1, laenge: 58.8, art: "flug", logo: /qantas|logo/i },
  a321: { achse: "z", nase: 1, laenge: 44.5, art: "flug" },
  a319: { achse: "z", nase: 1, laenge: 33.8, art: "flug" },
  global: { achse: "z", nase: 1, laenge: 33.8, art: "flug" },
  h225: { achse: "z", nase: 1, laenge: 18.7, art: "heli" },
  sklasse: { achse: "z", nase: 1, laenge: 5.47, art: "auto", lack: /paint/i },
  a8: { achse: "z", nase: -1, laenge: 5.45, art: "auto", lack: /a8texture12__(prim|sec)/i },
  bmw7: { achse: "x", nase: 1, laenge: 5.39, art: "auto", lack: /paint|body|AliceBlue/i },
  vklasse: { achse: "z", nase: 1, laenge: 5.14, art: "auto", lack: /carpaint/i },
  sprinter: { achse: "z", nase: 1, laenge: 5.93, art: "auto", lack: /CarPaint|FrontColor/i },
};

// Farbige Lackflächen der Textur (Airline-Farben) weiß machen; Fenster, Türen, Grau- und Schwarztöne bleiben
function ausbleichen(tex, art) {
  const img = tex && tex.image;
  if (!img || !img.width) return tex;
  const [c, g] = leinwand(img.width, img.height);
  g.drawImage(img, 0, 0);
  const d = g.getImageData(0, 0, c.width, c.height), p = d.data;
  for (let i = 0; i < p.length; i += 4) {
    const r = p[i], gg = p[i + 1], b = p[i + 2], mx = Math.max(r, gg, b), mn = Math.min(r, gg, b);
    const v = mx / 255, s = mx ? (mx - mn) / mx : 0;
    let weiss = s > 0.25 && v > 0.22;
    if (art === "heli") weiss = (v > 0.12 && v < 0.8 && !(b > r + 25 && b > gg + 10)) || weiss;   // Tarnanstrich → weiß, blaue Scheiben bleiben
    if (weiss) { const h = 236 + Math.round(v * 12); p[i] = h; p[i + 1] = h + 1; p[i + 2] = h + 3; }
  }
  g.putImageData(d, 0, 0);
  const t = tex.clone(); t.image = c; t.needsUpdate = true;
  return t;
}

function bildLaden(url) {
  return new Promise(ok => { const i = new Image(); i.onload = () => ok(i); i.onerror = () => ok(null); i.src = url; });
}

// Abziehbild: Leinwand → Textur, auf alle Meshes projiziert, die den Kasten schneiden
const DECAL_MATS = [];
function abziehbild(wurzel, canvas, pos, dreh, groesse) {
  const t = new THREE.CanvasTexture(canvas); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8;
  const m = new THREE.MeshPhysicalMaterial({ map: t, transparent: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -4, roughness: 0.35, clearcoat: 0.5 });
  DECAL_MATS.push(m);
  const kasten = new THREE.Box3().setFromCenterAndSize(pos, new THREE.Vector3(Math.max(groesse.x, groesse.z) * 1.5, groesse.y * 1.5, Math.max(groesse.x, groesse.z) * 1.5));
  const ziele = [];
  wurzel.traverse(o => { if (o.isMesh && !o.userData.decal && o.visible) { const b = new THREE.Box3().setFromObject(o); if (b.intersectsBox(kasten)) ziele.push(o); } });
  for (const z of ziele) {
    const geo = new DecalGeometry(z, pos, dreh, groesse);
    if (!geo.attributes.position || geo.attributes.position.count === 0) continue;
    const dm = new THREE.Mesh(geo, m); dm.userData.decal = true; dm.renderOrder = 2;
    szene.add(dm);
  }
}

// Strahl gegen das Modell: erster Treffer von außen
const strahl = new THREE.Raycaster();
function treffer(wurzel, von, richtung) {
  strahl.set(von, richtung.clone().normalize());
  const t = strahl.intersectObject(wurzel, true).find(h => !h.object.userData.decal);
  return t ? t.point : null;
}

function textLeinwand(zeilen, b = 2048, h = 256) {
  const [c, ctx] = leinwand(b, h);
  for (const z of zeilen) {
    let gr = z.groesse;
    const setzen = () => { ctx.font = `${z.gewicht || 700} ${gr}px "Segoe UI", Roboto, Arial, sans-serif`; ctx.letterSpacing = `${(z.abstand ?? 0.15) * gr}px`; };
    ctx.save(); ctx.fillStyle = z.farbe; setzen();
    while (gr > 20 && ctx.measureText(z.text).width > b * 0.94) { gr *= 0.92; setzen(); }
    ctx.textAlign = z.align || "left"; ctx.textBaseline = "middle";
    ctx.fillText(z.text, z.x, z.y); ctx.restore();
  }
  return c;
}

async function glbBauen(typ) {
  const cfg = MODELLE[typ];
  const lader = new GLTFLoader(); lader.setMeshoptDecoder(MeshoptDecoder);
  const gltf = await lader.loadAsync(`${D.basis}modelle/${typ}.glb?v=${D.v || 1}`);
  const roh = gltf.scene;
  // Ausrichten: Längsachse → x, Nase → -x; auf echte Länge skalieren; Mitte in den Ursprung, Unterkante auf y = boden
  const halter = new THREE.Group(); halter.add(roh);
  if (cfg.achse === "z") roh.rotation.y = cfg.nase > 0 ? -Math.PI / 2 : Math.PI / 2;
  else if (cfg.nase > 0) roh.rotation.y = Math.PI;
  halter.updateMatrixWorld(true);
  let box = new THREE.Box3().setFromObject(halter);
  const s = cfg.laenge / (box.max.x - box.min.x);
  roh.scale.multiplyScalar(s); halter.updateMatrixWorld(true);
  box = new THREE.Box3().setFromObject(halter);
  const mitte = box.getCenter(new THREE.Vector3());
  roh.position.sub(new THREE.Vector3(mitte.x, box.min.y, mitte.z).divideScalar(1));
  halter.updateMatrixWorld(true);
  box = new THREE.Box3().setFromObject(halter);
  szene.add(halter); halter.updateMatrixWorld(true);
  const L = cfg.laenge, Hh = box.max.y - box.min.y, ak = "#" + AKZENT.getHexString();

  // Materialien: Flugzeuge ausbleichen, Logos ersetzen; Autos: Lack einfärben
  const S = cfg.art === "auto" ? D.sonder : null;
  const lackFarbe = S ? (S.grund || "#eef0f3") : (D.farbe || "#0c0f14");
  roh.traverse(o => {
    if (!o.isMesh) return;
    const vc = o.geometry.attributes.color;
    if (vc && cfg.art !== "auto") {   // Eckpunktfarben (Rumpf-Lackierung mancher Modelle) ebenfalls ausbleichen
      const c = new THREE.Color(), hsl = {};
      for (let i = 0; i < vc.count; i++) { c.fromBufferAttribute(vc, i); c.getHSL(hsl); if (hsl.s > 0.25 && hsl.l > 0.12) vc.setXYZ(i, 0.93, 0.94, 0.95); }
      vc.needsUpdate = true;
    }
    o.material = [].concat(o.material).map(m => {
      const name = (m.name || "") + " " + o.name;
      if (cfg.logo && cfg.logo.test(name)) return lack(AKZENT, 0.3);
      if (cfg.art !== "auto") {
        m = m.clone();
        if (m.map) m.map = ausbleichen(m.map, cfg.art);
        const hsl = {}; m.color.getHSL(hsl);
        if (hsl.s > 0.25 && hsl.l > 0.12 && hsl.l < 0.9) m.color.set(0xf2f3f5);   // Airline-Farbe → Weiß
        if (cfg.art === "heli") { m.color.set(0xffffff); m.metalness = Math.min(m.metalness, 0.2); m.roughness = 0.45; }
        return m;
      }
      if (cfg.lack && cfg.lack.test(name)) { const n = lack(lackFarbe, 0.2); n.name = m.name; return n; }
      return m;
    });
    if (o.material.length === 1) o.material = o.material[0];
  });

  const nase = x => -L / 2 + x * L;   // Anteil der Länge ab der Nase → x
  if (cfg.art !== "auto") {
    // Rumpf vermessen: oben/unten bei 35 % und Seite (z) in Rumpfmitte
    const fx = nase(0.35), oben = treffer(halter, new THREE.Vector3(fx, box.max.y + 5, 0), new THREE.Vector3(0, -1, 0));
    const unten = treffer(halter, new THREE.Vector3(fx, box.min.y - 5, 0), new THREE.Vector3(0, 1, 0));
    const yO = oben ? oben.y : box.min.y + Hh * 0.6, yU = unten ? unten.y : box.min.y + Hh * 0.2;
    const Dm = yO - yU, yM = (yO + yU) / 2;
    const gross = cfg.art === "heli";
    for (const seite of [1, -1]) {
      const dreh = new THREE.Euler(0, seite > 0 ? 0 : Math.PI, 0);
      const seitlich = (x, y) => treffer(halter, new THREE.Vector3(x, y, seite * (Dm * 4 + 10)), new THREE.Vector3(0, 0, -seite));
      // Titel über den Fenstern
      const tx = nase(gross ? 0.42 : 0.33), ty = yM + Dm * (gross ? 0.05 : 0.26);
      const p1 = seitlich(tx, ty);
      if (p1) abziehbild(halter, textLeinwand([{ text: "IMPERIUM GERMANICUM", x: 1024, y: 128, groesse: 150, farbe: "#1a2230", align: "center", abstand: 0.2 }]),
        p1, dreh, new THREE.Vector3(L * (gross ? 0.36 : 0.3), Dm * (gross ? 0.12 : 0.14), Dm * 0.3));
      // Behördenname unter den Fenstern
      const p2 = seitlich(tx, yM - Dm * (gross ? 0.12 : 0.06));
      if (p2) abziehbild(halter, textLeinwand([{ text: (D.behoerde || "").toUpperCase(), x: 1024, y: 128, groesse: 104, farbe: ak, align: "center", gewicht: 600, abstand: 0.14 }]),
        p2, dreh, new THREE.Vector3(L * (gross ? 0.36 : 0.26), Dm * 0.09, Dm * 0.3));
      // Zierlinie Schwarz-Gold entlang des Rumpfs
      const [zc, zx] = leinwand(2048, 64); zx.fillStyle = SCHWARZ; zx.fillRect(0, 0, 2048, 28); zx.fillStyle = GOLD; zx.fillRect(0, 30, 2048, 34);
      const p3 = seitlich(nase(0.47), yM - Dm * 0.2);
      if (p3 && !gross) abziehbild(halter, zc, p3, dreh, new THREE.Vector3(L * 0.72, Dm * 0.05, Dm * 0.45));
      // Kennung am Heck, Taufname an der Nase
      const p4 = seitlich(nase(0.8), yM + Dm * 0.08);
      if (p4 && D.kennung) abziehbild(halter, textLeinwand([{ text: D.kennung, x: 1024, y: 128, groesse: 170, farbe: "#2a3140", align: "center", abstand: 0.06 }]),
        p4, dreh, new THREE.Vector3(L * 0.1, Dm * 0.11, Dm * 0.3));
      const p5 = seitlich(nase(0.13), yM + Dm * 0.06);
      if (p5 && D.name && !gross) abziehbild(halter, textLeinwand([{ text: D.name, x: 1024, y: 128, groesse: 130, farbe: "#2a3140", align: "center", gewicht: 500, abstand: 0.02 }]),
        p5, dreh, new THREE.Vector3(L * 0.1, Dm * 0.07, Dm * 0.3));
    }
    // Leitwerk: Hausfarbe, Goldband, weißer Reichsadler
    const finX = nase(gross ? 0.93 : 0.91), finUnten = yO + Dm * 0.12, finOben = box.max.y;
    const [fc, fx2] = leinwand(1024, 1024);
    fx2.fillStyle = ak; fx2.fillRect(0, 0, 1024, 1024); fx2.fillStyle = GOLD; fx2.fillRect(0, 210, 1024, 44); fx2.fillStyle = SCHWARZ; fx2.fillRect(0, 254, 1024, 26);
    adler(fx2, 512, 610, 420, "#ffffff");
    if (finOben > finUnten) abziehbild(halter, fc, new THREE.Vector3(finX, (finUnten + finOben) / 2, 0), new THREE.Euler(0, 0, 0),
      new THREE.Vector3(L * (gross ? 0.14 : 0.2), finOben - finUnten, Dm * 1.2));
  } else {
    // Straßenfahrzeuge: Standarten (Leitung), Behördenstreifen und Blaulicht (Polizei, Zoll, KatS)
    const W2 = (box.max.z - box.min.z) / 2;
    if (S) {
      for (const seite of [1, -1]) {
        const dreh = new THREE.Euler(0, seite > 0 ? 0 : Math.PI, 0);
        const p = treffer(halter, new THREE.Vector3(0, box.min.y + Hh * 0.42, seite * (W2 + 3)), new THREE.Vector3(0, 0, -seite));
        if (!p) continue;
        const [sc, sx] = leinwand(2048, 256);
        sx.fillStyle = S.streifen; sx.fillRect(0, 40, 2048, 150); sx.fillStyle = S.zweit || S.streifen; sx.fillRect(0, 190, 2048, 30);
        sx.fillStyle = "#fff"; sx.font = '800 108px "Segoe UI", Roboto, Arial, sans-serif'; sx.textAlign = "center"; sx.textBaseline = "middle"; sx.letterSpacing = "14px";
        sx.fillText(S.text, 1024, 118);
        abziehbild(halter, sc, p, dreh, new THREE.Vector3(L * 0.92, Hh * 0.2, W2 * 0.3));
      }
      const dachY = treffer(halter, new THREE.Vector3(nase(0.45), box.max.y + 3, 0), new THREE.Vector3(0, -1, 0));
      const balken = new THREE.Mesh(new THREE.BoxGeometry(0.28, 0.1, W2 * 1.1), new THREE.MeshStandardMaterial({ color: S.licht || 0x1e5bff, emissive: S.licht || 0x1e5bff, emissiveIntensity: 1.3 }));
      balken.position.set(nase(0.45), (dachY ? dachY.y : box.max.y) + 0.05, 0); szene.add(balken);
    } else if (typ !== "vklasse" && typ !== "sprinter") {
      // Fahne: persönliche Standarte der Leitung (z. B. Kronkanzler, quadratisch) oder allgemeine Adler-Fahne
      let ft, fb = 0.26, fh = 0.16;
      const st = D.standarte ? await bildLaden(D.standarte) : null;
      if (st) {
        const [fc, fx] = leinwand(256, 256); fx.drawImage(st, 0, 0, 256, 256);
        ft = textur(fc); ft.flipY = true; fb = 0.22; fh = 0.22;
      } else {
        const [fc, fx] = leinwand(256, 160);
        fx.fillStyle = GOLD; fx.fillRect(0, 0, 256, 160); fx.fillStyle = SCHWARZ; fx.fillRect(0, 0, 256, 18); fx.fillRect(0, 142, 256, 18);
        adler(fx, 128, 80, 120, SCHWARZ);
        ft = textur(fc); ft.flipY = true;
      }
      for (const seite of [1, -1]) {
        const vx = nase(0.1), oben = treffer(halter, new THREE.Vector3(vx, box.max.y + 3, seite * W2 * 0.72), new THREE.Vector3(0, -1, 0));
        const y0 = oben ? oben.y : box.min.y + Hh * 0.55;
        const stab = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, 0.2 + fh, 8), chrom); stab.position.set(vx, y0 + (0.2 + fh) / 2, seite * W2 * 0.72);
        const fahne = new THREE.Mesh(new THREE.PlaneGeometry(fb, fh), new THREE.MeshStandardMaterial({ map: ft, side: THREE.DoubleSide, roughness: 0.8 }));
        fahne.position.set(vx + fb / 2 + 0.01, y0 + 0.2 + fh / 2 - 0.02, seite * W2 * 0.72); szene.add(stab, fahne);
      }
    }
  }
  return { modell: halter, groesse: cfg.art === "auto" ? L * 1.25 : Math.max(L, box.max.z - box.min.z), boden: cfg.art === "auto" };
}

// ------------------------------------------------------------ Aufbau
async function bauen() {
  await adlerGeladen;
  let e;
  if (MODELLE[D.typ]) {
    try { e = await glbBauen(D.typ); }
    catch (err) { console.warn("Modell nicht geladen, eigenes Modell als Ersatz:", err); e = null; }
  }
  if (!e) {
    if (FLUGZEUGE[D.typ]) e = flugzeug(FLUGZEUGE[D.typ]);
    else if (D.typ === "h225") e = hubschrauber();
    else e = wagen(WAGEN[D.typ] || WAGEN.sklasse);
  }
  szene.add(e.modell);
  // Bodenschatten (weicher Kreis) unter dem Modell
  const [c, g] = leinwand(256, 256);
  const rg = g.createRadialGradient(128, 128, 10, 128, 128, 128); rg.addColorStop(0, "rgba(16,24,40,.38)"); rg.addColorStop(1, "rgba(16,24,40,0)");
  g.fillStyle = rg; g.fillRect(0, 0, 256, 256);
  const st = new THREE.CanvasTexture(c);
  const schatten = new THREE.Mesh(new THREE.PlaneGeometry(e.groesse * 0.9, e.groesse * (e.boden ? 0.5 : 0.75)), new THREE.MeshBasicMaterial({ map: st, transparent: true, depthWrite: false }));
  schatten.rotation.x = -Math.PI / 2;
  const box = new THREE.Box3().setFromObject(e.modell);
  schatten.position.y = box.min.y - (e.boden ? 0.0 : e.groesse * 0.08);
  szene.add(schatten);
  const mitte = box.getCenter(new THREE.Vector3());
  steuerung.target.copy(mitte);
  ansicht("schraeg", e.groesse, mitte);
  document.querySelectorAll("[data-ansicht]").forEach(b => b.addEventListener("click", () => ansicht(b.dataset.ansicht, e.groesse, mitte)));
  huelle.classList.add("fertig");
}
function ansicht(art, gr, m) {
  const d = gr * 1.35 * Math.max(1, 1.3 / (W() / H()));   // Hochformat (Handy): weiter weg, damit das ganze Fahrzeug passt
  const ziele = { schraeg: [-0.75, 0.32, 0.85], seite: [0, 0.05, 1], vorne: [-1, 0.12, 0.02], oben: [0.001, 1, 0.001] };
  const z = ziele[art] || ziele.schraeg;
  const v = new THREE.Vector3(...z).normalize().multiplyScalar(d);
  kamera.position.copy(m).add(v); kamera.near = d / 100; kamera.far = d * 20; kamera.updateProjectionMatrix();
  steuerung.update();
}
const dreh = document.getElementById("fz-dreh");
if (dreh) { dreh.setAttribute("aria-pressed", String(steuerung.autoRotate)); dreh.addEventListener("click", () => { steuerung.autoRotate = !steuerung.autoRotate; dreh.setAttribute("aria-pressed", String(steuerung.autoRotate)); }); }
steuerung.addEventListener("start", () => { steuerung.autoRotate = false; dreh && dreh.setAttribute("aria-pressed", "false"); });
new ResizeObserver(() => { renderer.setSize(W(), H()); kamera.aspect = W() / H(); kamera.updateProjectionMatrix(); }).observe(huelle);
const uhr = new THREE.Clock();
renderer.setAnimationLoop(() => {
  const dt = uhr.getDelta();
  if (rotor) rotor.rotation.y += dt * 6; if (heckrotor) heckrotor.rotation.z += dt * 18;
  steuerung.update(); renderer.render(szene, kamera);
});
bauen();
