/**
 * Camera Bot — separate Minecraft connection for headless first-person recording.
 *
 * Connects as a second bot, TELEPORTS to stay near the main bot, and streams
 * rendered frames via TCP to the Python FrameReceiver at configured FPS.
 *
 * Usage:
 *   node camera_bot.js --host 127.0.0.1 --port 55916 --target ANNIE_Bot --record-port 8089
 */

import mineflayer from 'mineflayer';
import mcDataPkg from 'minecraft-data';
import { Vec3 } from 'vec3';

const args = process.argv.slice(2);
const config = {
    fps: 8, width: 854, height: 480,
    viewDistance: 32, jpegQuality: 92
};
for (let i = 0; i < args.length; i++) {
    if (args[i] === '--host') config.host = args[++i];
    else if (args[i] === '--port') config.port = parseInt(args[++i], 10);
    else if (args[i] === '--target') config.target = args[++i];
    else if (args[i] === '--record-port') config.recordPort = parseInt(args[++i], 10);
    else if (args[i] === '--fps') config.fps = parseInt(args[++i], 10);
    else if (args[i] === '--width') config.width = parseInt(args[++i], 10);
    else if (args[i] === '--height') config.height = parseInt(args[++i], 10);
    else if (args[i] === '--quality') config.jpegQuality = parseInt(args[++i], 10);
}

if (!config.host || !config.port || !config.target || !config.recordPort) {
    process.stderr.write('Usage: node camera_bot.js --host H --port P --target NAME --record-port P [--fps 8] [--width 854] [--height 480]\n');
    process.exit(1);
}

const { fps, width, height, viewDistance, jpegQuality } = config;
const FRAME_INTERVAL = Math.round(1000 / fps);

// ── Load rendering modules ────────────────────────────────────────────────
import THREE from 'three';
global.THREE = THREE;
import { createCanvas } from 'node-canvas-webgl/lib/index.js';
import { Viewer } from 'prismarine-viewer/viewer/lib/viewer.js';
import { WorldView } from 'prismarine-viewer/viewer/lib/worldView.js';
import { getBufferFromStream } from 'prismarine-viewer/viewer/lib/simpleUtils.js';
import worker_threads from 'worker_threads';
global.Worker = worker_threads.Worker;
import net from 'net';

// ── Create camera bot ─────────────────────────────────────────────────────
const bot = mineflayer.createBot({
    host: config.host, port: config.port,
    username: 'ANNIE_Camera', auth: 'offline',
});

let mcData = null;
bot.once('inject_allowed', () => { mcData = mcDataPkg(bot.version); });

let viewer, worldView, canvas, renderer;
let clientSocket = null;
let targetEntity = null;
let frameIndex = 0;
let lastTargetPos = null;
let lastTargetYaw = 0, lastTargetPitch = 0;

function initRenderer() {
    canvas = createCanvas(width, height);
    renderer = new THREE.WebGLRenderer({ canvas });
    viewer = new Viewer(renderer);
    viewer.setVersion(bot.version);
    process.stderr.write(`[camera] Renderer ${width}x${height}\n`);
}

async function initWorld() {
    const center = bot.entity.position.clone();
    worldView = new WorldView(bot.world, viewDistance, center);
    viewer.listen(worldView);
    worldView.listenToBot(bot);
    await worldView.init(center);
    process.stderr.write(`[camera] World ready, view=${viewDistance}\n`);
}

function connectToReceiver() {
    return new Promise((resolve, reject) => {
        clientSocket = new net.Socket();
        clientSocket.connect(config.recordPort, '127.0.0.1', () => {
            process.stderr.write(`[camera] Connected to :${config.recordPort}\n`);
            resolve();
        });
        clientSocket.on('error', reject);
    });
}

let targetFound = false;

function findTarget() {
    if (bot.players[config.target]) {
        const entity = bot.players[config.target].entity;
        if (entity && entity.position) {
            if (!targetFound) {
                process.stderr.write(`[camera] FOUND target: ${config.target} at ${entity.position}\n`);
                targetFound = true;
            }
            targetEntity = entity;
            return;
        }
    }
}

function followTarget() {
    if (!targetEntity || !targetEntity.position) return;
    const tp = targetEntity.position;

    // Teleport if more than 3 blocks away
    if (!lastTargetPos || lastTargetPos.distanceTo(tp) > 3) {
        bot.entity.position.set(tp.x, tp.y + 0.1, tp.z);
        lastTargetPos = tp.clone();
        lastTargetYaw = targetEntity.yaw || 0;
        lastTargetPitch = targetEntity.pitch || 0;
        process.stderr.write(`[camera] Teleported to (${tp.x.toFixed(0)},${tp.y.toFixed(0)},${tp.z.toFixed(0)})\n`);
    }
}

// ── Render and send one frame ─────────────────────────────────────────────
function captureAndSend() {
    // Try to find target on every frame
    findTarget();
    if (targetEntity) followTarget();

    if (!viewer || !worldView || !clientSocket || clientSocket.destroyed) {
        scheduleNext(); return;
    }

    try {
        // Use target position if available, otherwise camera bot's own position
        let camPos, camYaw, camPitch;
        if (lastTargetPos) {
            // Render from target's eye position (eyes are ~1.6 blocks above feet)
            camPos = new Vec3(lastTargetPos.x, lastTargetPos.y + 1.6, lastTargetPos.z);
            camYaw = lastTargetYaw;
            camPitch = lastTargetPitch;
        } else {
            const bp = bot.entity.position;
            camPos = new Vec3(bp.x, bp.y + 1.6, bp.z);
            camYaw = bot.entity.yaw;
            camPitch = bot.entity.pitch;
        }

        viewer.setFirstPersonCamera(camPos, camYaw, camPitch);
        worldView.updatePosition(camPos);
        viewer.update();
        renderer.render(viewer.scene, viewer.camera);

        const imageStream = canvas.createJPEGStream({
            bufsize: 4096, quality: jpegQuality, progressive: false,
        });

        getBufferFromStream(imageStream).then((buffer) => {
            if (!clientSocket || clientSocket.destroyed) { scheduleNext(); return; }
            try {
                const sizeBuf = Buffer.alloc(4);
                sizeBuf.writeUInt32LE(buffer.length, 0);
                clientSocket.write(sizeBuf);
                clientSocket.write(buffer);
                frameIndex++;
                if (frameIndex <= 3 || frameIndex % (fps * 5) === 0) {
                    process.stderr.write(`[camera] frame ${frameIndex}: ${buffer.length}B ` +
                        `pos=(${camPos.x.toFixed(0)},${camPos.y.toFixed(0)},${camPos.z.toFixed(0)})\n`);
                }
            } catch (err) {
                process.stderr.write(`[camera] Send err: ${err.message}\n`);
            }
            scheduleNext();
        }).catch((err) => {
            process.stderr.write(`[camera] JPEG err: ${err.message}\n`);
            scheduleNext();
        });
    } catch (err) {
        process.stderr.write(`[camera] Render err: ${err.message}\n`);
        scheduleNext();
    }
}

function scheduleNext() {
    if (!clientSocket || clientSocket.destroyed) return;
    setTimeout(captureAndSend, FRAME_INTERVAL);
}

// ── Startup ────────────────────────────────────────────────────────────────
bot.once('spawn', async () => {
    process.stderr.write(`[camera] Spawned at ${bot.entity.position}\n`);
    try {
        initRenderer();
        await initWorld();
        await connectToReceiver();

        // Start frame capture loop (findTarget is called from captureAndSend)
        scheduleNext();
        process.stderr.write(`[camera] Recording ${width}x${height} @${fps}fps q=${jpegQuality} view=${viewDistance}\n`);
    } catch (err) {
        process.stderr.write(`[camera] Fatal: ${err.message}\n${err.stack}\n`);
        process.exit(1);
    }
});

bot.on('error', (err) => process.stderr.write(`[camera] Bot err: ${err.message}\n`));

process.on('SIGTERM', () => {
    if (clientSocket) clientSocket.end();
    try { bot.quit(); } catch (_) {}
    process.exit(0);
});
process.on('SIGINT', () => {
    if (clientSocket) clientSocket.end();
    try { bot.quit(); } catch (_) {}
    process.exit(0);
});
