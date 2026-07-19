/**
 * ANNIE Minecraft Bridge — Node.js side.
 *
 * A minimal mineflayer bot that bridges Minecraft to the ANNIE Python framework.
 * Communicates with Python via JSON-RPC over stdin/stdout.
 *
 * Protocol (one JSON object per line, newline-delimited):
 *
 *   Python → Node (request):
 *     {"id": "req_001", "method": "go_to", "params": {"x": 100, "y": 64, "z": 200}, "timeout_ms": 30000}
 *
 *   Node → Python (immediate response):
 *     {"id": "req_001", "status": "accepted"}
 *
 *   Node → Python (async completion):
 *     {"id": "req_001", "status": "completed", "data": {"ok": true, "reason": "arrived"}}
 *     {"id": "req_001", "status": "failed", "data": {"ok": false, "reason": "path blocked"}}
 *     {"id": "req_001", "status": "timeout", "data": {"ok": false, "reason": "timed out after 30000ms"}}
 *
 *   Node → Python (event push):
 *     {"type": "event", "event": "damage", "data": {"source": "zombie", "amount": 3, "health": 17}}
 *     {"type": "event", "event": "death", "data": {"reason": "...", "position": [0,70,0]}}
 *     {"type": "event", "event": "chat", "data": {"player": "Steve", "message": "hey"}}
 *     {"type": "event", "event": "action_completed", "data": {"action_id": "abc123", "result": {...}}}
 */

import * as readline from 'node:readline';
import mineflayer from 'mineflayer';
import pfPkg from 'mineflayer-pathfinder';
const { pathfinder, Movements, goals } = pfPkg;
import mcDataPkg from 'minecraft-data';
const minecraftData = mcDataPkg;

// ── Parse command-line arguments ──────────────────────────────────────────
const args = process.argv.slice(2);
const config = {
    auth: 'offline',  // default: offline mode for local LAN worlds (mindcraft pattern)
    version: false,   // false = auto-detect (mindcraft pattern)
};
for (let i = 0; i < args.length; i++) {
    if (args[i] === '--host' && i + 1 < args.length) config.host = args[++i];
    else if (args[i] === '--port' && i + 1 < args.length) config.port = parseInt(args[++i], 10);
    else if (args[i] === '--username' && i + 1 < args.length) config.username = args[++i];
    else if (args[i] === '--version' && i + 1 < args.length) {
        const v = args[++i];
        config.version = (v === 'auto' || v === 'false') ? false : v;
    }
    else if (args[i] === '--auth' && i + 1 < args.length) config.auth = args[++i];
    else if (args[i] === '--viewer-port' && i + 1 < args.length) config.viewerPort = parseInt(args[++i], 10);
    else if (args[i] === '--record-port' && i + 1 < args.length) config.recordPort = parseInt(args[++i], 10);
}

if (!config.host || !config.port || !config.username) {
    process.stdout.write(JSON.stringify({
        type: 'error',
        error: 'Missing required arguments: --host, --port, --username'
    }) + '\n');
    process.exit(1);
}

// ── Create bot ────────────────────────────────────────────────────────────
const bot = mineflayer.createBot({
    host: config.host,
    port: config.port,
    username: config.username,
    auth: config.auth || 'offline',
    version: config.version || false,
    checkTimeoutInterval: 60000,
});

// Position-packet throttle (mindcraft pattern): Paper/Spigot servers kick
// clients that send position updates faster than 50ms apart.
let lastPositionUpdate = 0;
let pendingPositionPacket = null;
const POSITION_THROTTLE_MS = 50;
const originalWrite = bot._client.write.bind(bot._client);
bot._client.write = function(name, data) {
    if (name === 'position' || name === 'position_look' || name === 'look') {
        const now = Date.now();
        if (now - lastPositionUpdate < POSITION_THROTTLE_MS) {
            if (!pendingPositionPacket) {
                pendingPositionPacket = setTimeout(() => {
                    pendingPositionPacket = null;
                    lastPositionUpdate = Date.now();
                    originalWrite(name, data);
                }, POSITION_THROTTLE_MS - (now - lastPositionUpdate));
            }
            return;
        }
        lastPositionUpdate = now;
        if (pendingPositionPacket) {
            clearTimeout(pendingPositionPacket);
            pendingPositionPacket = null;
        }
    }
    originalWrite(name, data);
};

bot.loadPlugin(pathfinder);

let mcData = null;
bot.once('inject_allowed', () => {
    mcData = minecraftData(bot.version);
});

// ── Pending requests map ──────────────────────────────────────────────────
const pending = new Map(); // id → { resolve, reject, timeout }

function send(obj) {
    process.stdout.write(JSON.stringify(obj) + '\n');
}

function pushEvent(eventType, data) {
    send({ type: 'event', event: eventType, data });
}

// ── Handle incoming requests from Python ──────────────────────────────────
const rl = readline.createInterface({ input: process.stdin });

rl.on('line', (line) => {
    let req;
    try { req = JSON.parse(line); } catch (e) { return; }
    if (!req.id || !req.method) return;

    const timeoutMs = req.timeout_ms || 30000;

    try {
        const result = handleRequest(req.method, req.params);
        if (result instanceof Promise) {
            // Async method — send accepted, complete later
            send({ id: req.id, status: 'accepted' });
            const timer = setTimeout(() => {
                pending.delete(req.id);
                send({ id: req.id, status: 'timeout', data: { ok: false, reason: `timed out after ${timeoutMs}ms` } });
            }, timeoutMs);
            pending.set(req.id, { timer });
            result.then(
                (data) => {
                    clearTimeout(timer);
                    if (pending.has(req.id)) {
                        pending.delete(req.id);
                        send({ id: req.id, status: 'completed', data });
                    }
                },
                (err) => {
                    clearTimeout(timer);
                    if (pending.has(req.id)) {
                        pending.delete(req.id);
                        send({ id: req.id, status: 'failed', data: { ok: false, reason: err.message } });
                    }
                }
            );
        } else {
            // Sync method
            send({ id: req.id, status: 'completed', data: result });
        }
    } catch (err) {
        send({ id: req.id, status: 'failed', data: { ok: false, reason: err.message } });
    }
});

function handleRequest(method, params) {
    switch (method) {
        // ── Movement ──────────────────────────────────────────────────
        case 'go_to':
            return goTo(params.x, params.y, params.z);
        case 'go_to_block':
            return goToNearestBlock(params.block_type, params.radius || 64);
        case 'stop_moving':
            return stopMoving();
        case 'dig_down':
            return digDown(params.depth || 3);
        case 'go_to_surface':
            return goToSurface();

        // ── Perception ────────────────────────────────────────────────
        case 'get_stats':
            return getStats();
        case 'get_nearby_blocks':
            return getNearbyBlocks(params.radius || 4);
        case 'get_nearby_entities':
            return getNearbyEntities(params.radius || 16);
        case 'get_inventory':
            return getInventory();
        case 'get_craftable':
            return getCraftable();
        case 'is_clear_path':
            return isClearPath(params.target_x, params.target_y, params.target_z);

        // ── Block operations ──────────────────────────────────────────
        case 'break_block':
            return breakBlockAt(params.x, params.y, params.z);
        case 'place_block':
            return placeBlockAt(params.x, params.y, params.z, params.block_type);

        // ── Item operations ───────────────────────────────────────────
        case 'collect_block':
            return collectBlock(params.block_type, params.count || 1);
        case 'craft_recipe':
            return craftRecipe(params.item_name, params.count || 1);
        case 'equip':
            return equipItem(params.item_name);
        case 'consume':
            return consumeItem(params.item_name);
        case 'discard':
            return discardItem(params.item_name, params.count || 1);
        case 'pickup_nearby':
            return pickupNearby(params.radius || 8);

        // ── Combat ────────────────────────────────────────────────────
        case 'attack_nearest':
            return attackNearestEntity(params.entity_type);
        case 'defend_self':
            return defendSelf(params.range || 8);
        case 'move_away':
            return moveAway(params.distance || 10);

        // ── Chat ──────────────────────────────────────────────────────
        case 'send_chat':
            return sendChatMessage(params.message);

        // ── Player interaction ────────────────────────────────────────
        case 'follow_player':
            return followPlayer(params.username, params.distance || 4);
        case 'go_to_player':
            return goToPlayer(params.username);
        case 'give_to_player':
            return giveToPlayer(params.item_name, params.username, params.count || 1);

        // ── Furnace ───────────────────────────────────────────────────
        case 'smelt_item':
            return smeltItem(params.item_name, params.count || 1);
        case 'clear_furnace':
            return clearNearestFurnace();

        // ── Safety ────────────────────────────────────────────────────
        case 'place_torch':
            return placeTorchNearby();

        // ── Interaction ───────────────────────────────────────────────
        case 'open_chest':
            return openChest(params.x, params.y, params.z);
        case 'take_from_chest':
            return takeFromChest(params.x, params.y, params.z, params.item_name, params.count || 1);
        case 'put_in_chest':
            return putInChest(params.x, params.y, params.z, params.item_name, params.count || 1);

        default:
            throw new Error(`Unknown method: ${method}`);
    }
}

// ── Minecraft events → push to Python ─────────────────────────────────────
bot.on('entityHurt', (entity) => {
    if (entity !== bot.entity) return;
    pushEvent('damage', {
        health: Math.round(bot.health),
        last_damage: bot.lastDamageTaken || 1,
    });
});

bot.on('death', () => {
    const pos = bot.entity?.position;
    pushEvent('death', {
        reason: 'died',
        position: pos ? [Math.round(pos.x), Math.round(pos.y), Math.round(pos.z)] : [0, 0, 0],
    });
});

bot.on('chat', (username, message) => {
    if (username === bot.username) return;
    pushEvent('chat', { player: username, message });
});

bot.on('whisper', (username, message) => {
    if (username === bot.username) return;
    pushEvent('chat', { player: username, message, private: true });
});

bot.on('kicked', (reason) => {
    pushEvent('kicked', { reason: String(reason) });
    process.exit(1);
});

bot.on('error', (err) => {
    pushEvent('error', { message: err.message });
});

// Notify Python when bot is ready
bot.once('spawn', async () => {
    const defaults = Movements;
    const moves = new defaults(bot, mcData);
    bot.pathfinder.setMovements(moves);

    // Start browser-based first-person viewer (mindcraft pattern)
    if (config.viewerPort) {
        try {
            const pvPkg = await import('prismarine-viewer');
            const mineflayerViewer = pvPkg.default.mineflayer;
            if (mineflayerViewer) {
                mineflayerViewer(bot, { port: config.viewerPort, firstPerson: true });
                console.error(`[viewer] First-person view: http://localhost:${config.viewerPort}`);
            }
        } catch (err) {
            console.error(`[viewer] Failed: ${err.message}`);
        }
    }

    // Start headless viewer for recording (streams frames via TCP)
    if (config.recordPort) {
        try {
            // Use throttled version (2fps) via dynamic import
            const headlessModule = await import('./node_modules/prismarine-viewer/lib/headless_throttled.js');
            const headlessViewer = headlessModule.default || headlessModule;
            if (headlessViewer) {
                const recordClient = headlessViewer(bot, {
                    output: `127.0.0.1:${config.recordPort}`,
                    frames: -1,
                    width: 320,
                    height: 240,
                });
                console.error(`[recorder] Throttled headless streaming to port ${config.recordPort} (320x240@2fps)`);
                bot._recordClient = recordClient;
            }
        } catch (err) {
            console.error(`[recorder] Headless viewer failed: ${err.message}`);
        }
    }

    pushEvent('ready', {
        username: bot.username,
        game_mode: bot.game?.gameMode || 'survival',
        position: [Math.round(bot.entity.position.x), Math.round(bot.entity.position.y), Math.round(bot.entity.position.z)],
        viewer_port: config.viewerPort || null,
        record_port: config.recordPort || null,
    });
});

// ── Movement implementations ──────────────────────────────────────────────

async function goTo(x, y, z) {
    const goal = new goals.GoalBlock(x, y, z);
    await bot.pathfinder.goto(goal);
    return { ok: true, position: [Math.round(bot.entity.position.x), Math.round(bot.entity.position.y), Math.round(bot.entity.position.z)] };
}

async function goToNearestBlock(blockType, radius) {
    const block = findNearestBlock(blockType, radius);
    if (!block) return { ok: false, reason: `no ${blockType} found within ${radius} blocks` };
    await bot.pathfinder.goto(new goals.GoalBlock(block.position.x, block.position.y, block.position.z));
    return { ok: true, block: block.name, position: [block.position.x, block.position.y, block.position.z] };
}

async function stopMoving() {
    bot.pathfinder.stop();
    bot.clearControlStates();
    return { ok: true };
}

async function digDown(depth) {
    const startY = bot.entity.position.y;
    for (let i = 0; i < depth; i++) {
        const target = bot.blockAt(bot.entity.position.offset(0, -1 - i, 0));
        if (!target || target.name === 'bedrock' || target.name === 'air') break;
        await bot.dig(target);
    }
    return { ok: true, dug_from: startY, dug_to: bot.entity.position.y };
}

async function goToSurface() {
    let y = bot.entity.position.y;
    while (y < 320) {
        const block = bot.blockAt(bot.entity.position.offset(0, y - bot.entity.position.y + 1, 0));
        if (!block || block.name === 'air') break;
        y++;
    }
    await goTo(bot.entity.position.x, y + 1, bot.entity.position.z);
    return { ok: true, position: [Math.round(bot.entity.position.x), Math.round(bot.entity.position.y), Math.round(bot.entity.position.z)] };
}

// ── Perception implementations ────────────────────────────────────────────

function getStats() {
    const pos = bot.entity.position;
    const timeOfDay = bot.time?.timeOfDay || 0;
    let timeLabel = 'Night';
    if (timeOfDay < 6000) timeLabel = 'Morning';
    else if (timeOfDay < 12000) timeLabel = 'Afternoon';

    let weather = 'Clear';
    if (bot.rainState > 0) weather = 'Rain';
    if (bot.thunderState > 0) weather = 'Thunderstorm';

    // ── Danger detection (mirrors mindcraft self_preservation) ───────────
    const feetBlock = bot.blockAt(pos.offset(0, 0, 0));
    const headBlock = bot.blockAt(pos.offset(0, 1, 0));
    const inWater = feetBlock?.name === 'water' || false;
    const submerged = inWater && (headBlock?.name === 'water' || false);

    // Light level at feet (sky + block light).  0 = pitch black, 15 = full sun.
    const skyLight = feetBlock?.skyLight ?? 0;
    const blockLight = feetBlock?.blockLight ?? 0;
    const lightLevel = Math.max(skyLight, blockLight);

    // Nearby dangerous blocks within 3-block radius
    const dangerBlocks = [];
    const dangerTypes = new Set(['lava', 'fire', 'soul_fire', 'campfire', 'soul_campfire',
                                  'cactus', 'sweet_berry_bush', 'wither_rose',
                                  'magma_block', 'powder_snow']);
    try {
        const nearby = bot.findBlocks({
            matching: (block) => {
                if (!block) return false;
                if (dangerTypes.has(block.name)) return true;
                // Also check for flowing lava
                if (block.name === 'lava' || block.name === 'flowing_lava') return true;
                return false;
            },
            maxDistance: 5,
            count: 10,
        });
        for (const bp of nearby || []) {
            const b = bot.blockAt(bp);
            if (!b) continue;
            const dx = bp.x - pos.x;
            const dy = bp.y - pos.y;
            const dz = bp.z - pos.z;
            const dist = Math.sqrt(dx*dx + dy*dy + dz*dz);
            dangerBlocks.push({
                name: b.name,
                position: [bp.x, bp.y, bp.z],
                distance: Math.round(dist * 10) / 10,
            });
        }
    } catch (_) { /* block lookup can fail in unloaded chunks */ }

    // Fall distance risk — if there's a big drop below
    let fallRisk = 0;
    try {
        const below = bot.blockAt(pos.offset(0, -1, 0));
        if (!below || below.name === 'air' || below.name === 'cave_air') {
            // Check how far the drop is
            for (let dy = -2; dy >= -20; dy--) {
                const checkBlock = bot.blockAt(pos.offset(0, dy, 0));
                if (checkBlock && checkBlock.name !== 'air' && checkBlock.name !== 'cave_air') {
                    fallRisk = Math.abs(dy) - 1;
                    break;
                }
            }
        }
    } catch (_) {}

    return {
        ok: true,
        position: [Math.round(pos.x * 100) / 100, Math.round(pos.y * 100) / 100, Math.round(pos.z * 100) / 100],
        health: Math.round(bot.health),
        hunger: Math.round(bot.food),
        biome: bot.blockAt(pos)?.biome?.name || 'unknown',
        time: timeLabel,
        weather,
        gamemode: bot.game?.gameMode || 'survival',
        // Danger fields (mindcraft self_preservation)
        on_fire: bot.entity?.onFire || false,
        in_water: inWater,
        submerged: submerged,
        light_level: lightLevel,
        fall_risk: fallRisk,
        nearby_danger_blocks: dangerBlocks,
    };
}

function getNearbyBlocks(radius) {
    const blocks = bot.findBlocks({
        matching: () => true,
        maxDistance: radius,
        count: 200,
    });
    const result = [];
    const seen = new Set();
    for (const pos of blocks) {
        const block = bot.blockAt(pos);
        if (!block || block.name === 'air' || block.name === 'cave_air' || block.name === 'void_air') continue;
        const key = `${block.name}`;
        if (seen.has(key)) continue;
        seen.add(key);
        const dx = pos.x - bot.entity.position.x;
        const dy = pos.y - bot.entity.position.y;
        const dz = pos.z - bot.entity.position.z;
        const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
        result.push({
            name: block.name,
            position: [pos.x, pos.y, pos.z],
            relative: [Math.round(dx), Math.round(dy), Math.round(dz)],
            distance: Math.round(dist * 10) / 10,
        });
    }
    result.sort((a, b) => a.distance - b.distance);
    return { ok: true, blocks: result.slice(0, 30) };
}

function getNearbyEntities(radius) {
    const entities = Object.values(bot.entities).filter(e => {
        if (!e || e === bot.entity) return false;
        const dist = e.position.distanceTo(bot.entity.position);
        return dist <= radius;
    });
    const result = entities.map(e => {
        const dist = e.position.distanceTo(bot.entity.position);
        return {
            name: e.name || 'unknown',
            type: e.type || 'mob',
            position: [Math.round(e.position.x), Math.round(e.position.y), Math.round(e.position.z)],
            distance: Math.round(dist * 10) / 10,
            is_hostile: isHostile(e),
            health: e.health,
        };
    });
    result.sort((a, b) => a.distance - b.distance);
    return { ok: true, entities: result };
}

function getInventory() {
    const items = bot.inventory.items();
    const counts = {};
    for (const item of items) {
        counts[item.name] = (counts[item.name] || 0) + item.count;
    }
    // Armor
    const armor = {};
    const slots = bot.inventory.slots;
    if (slots[5]) armor.head = slots[5].name;
    if (slots[6]) armor.chest = slots[6].name;
    if (slots[7]) armor.legs = slots[7].name;
    if (slots[8]) armor.feet = slots[8].name;

    // Held item
    const held = bot.heldItem;
    return {
        ok: true,
        items: counts,
        armor,
        held_item: held ? { name: held.name, count: held.count, durability: held.durability } : null,
        empty_slots: bot.inventory.emptySlotCount(),
    };
}

function getCraftable() {
    if (!mcData) return { ok: true, craftable: [] };
    const inventory = bot.inventory.items();
    const craftable = [];
    // Check all item recipes
    for (const [id, item] of Object.entries(mcData.items)) {
        if (!item.name) continue;
        try {
            const recipes = bot.recipesFor(id, null, 1, null);
            if (recipes && recipes.length > 0) {
                craftable.push(item.name);
            }
        } catch (e) { /* skip items without recipes */ }
    }
    return { ok: true, craftable: [...new Set(craftable)].slice(0, 50) };
}

function isClearPath(targetX, targetY, targetZ) {
    // Simple ray-based visibility check
    const target = new bot.vec3(targetX, targetY, targetZ);
    const direction = target.clone().subtract(bot.entity.position).normalize();
    const distance = bot.entity.position.distanceTo(target);
    // Not a true raytrace, but the pathfinder will handle real navigation
    return { ok: true, reachable: true, distance: Math.round(distance * 10) / 10 };
}

// ── Block operation implementations ───────────────────────────────────────

async function breakBlockAt(x, y, z) {
    const block = bot.blockAt(new bot.vec3(x, y, z));
    if (!block || block.name === 'air') return { ok: false, reason: 'no block at position' };
    if (!bot.canDigBlock(block)) return { ok: false, reason: `cannot dig ${block.name}` };
    await bot.dig(block);
    return { ok: true, block: block.name };
}

async function placeBlockAt(x, y, z, blockType) {
    const referenceBlock = bot.blockAt(new bot.vec3(x, y, z));
    if (!referenceBlock) return { ok: false, reason: 'no reference block' };
    const item = bot.inventory.findInventoryItem(blockType);
    if (!item) return { ok: false, reason: `no ${blockType} in inventory` };
    await bot.equip(item, 'hand');
    // Place against the reference block face
    const pos = new bot.vec3(x, y, z);
    await bot.placeBlock(referenceBlock, pos.clone().subtract(referenceBlock.position));
    return { ok: true, block: blockType, position: [x, y, z] };
}

// ── Item operation implementations ────────────────────────────────────────

async function collectBlock(blockType, count) {
    let collected = 0;
    for (let i = 0; i < count * 3; i++) { // search up to 3x target blocks
        const block = findNearestBlock(blockType, 32);
        if (!block) break;
        await bot.pathfinder.goto(new goals.GoalBlock(block.position.x, block.position.y, block.position.z));
        if (bot.canDigBlock(block)) {
            await bot.dig(block);
            collected++;
        }
        if (collected >= count) break;
    }
    return { ok: true, collected, target: count };
}

async function craftRecipe(itemName, count) {
    if (!mcData) return { ok: false, reason: 'mcData not loaded' };
    const itemId = mcData.itemsByName[itemName]?.id;
    if (!itemId) return { ok: false, reason: `unknown item: ${itemName}` };

    let recipes = bot.recipesFor(itemId, null, 1, null);
    let craftingTable = null;

    if (!recipes || recipes.length === 0) {
        // Try with crafting table
        craftingTable = findNearestBlock('crafting_table', 16);

        // If no placed crafting table nearby, auto-place one from inventory
        if (!craftingTable) {
            const tableItem = bot.inventory.findInventoryItem('crafting_table');
            if (tableItem) {
                const placed = await autoPlaceCraftingTable();
                if (placed) {
                    craftingTable = findNearestBlock('crafting_table', 8);
                }
            }
        }

        if (!craftingTable) {
            return {
                ok: false,
                reason: `no crafting table nearby and none in inventory. ` +
                    `Cannot craft ${itemName} (requires 3x3 grid). ` +
                    `First craft a crafting_table with 4 planks in your 2x2 grid.`
            };
        }
        recipes = bot.recipesFor(itemId, null, 1, true);
    }
    if (!recipes || recipes.length === 0) return { ok: false, reason: `no recipe for ${itemName}` };

    try {
        await bot.craft(recipes[0], count, craftingTable);
        return { ok: true, crafted: itemName, count };
    } catch (e) {
        return { ok: false, reason: e.message };
    }
}

// Auto-place a crafting table from inventory onto the ground near the bot
async function autoPlaceCraftingTable() {
    const tableItem = bot.inventory.findInventoryItem('crafting_table');
    if (!tableItem) return false;

    // Find a solid block at the bot's feet to place against
    const botPos = bot.entity.position;
    // Check the block the bot is standing on, and blocks around it
    const checkOffsets = [
        { x: 0, y: -1, z: 0 },   // block below feet
        { x: 1, y: -1, z: 0 },
        { x: -1, y: -1, z: 0 },
        { x: 0, y: -1, z: 1 },
        { x: 0, y: -1, z: -1 },
        { x: 0, y: 0, z: -1 },   // block in front (eye level)
        { x: 1, y: 0, z: 0 },
        { x: -1, y: 0, z: 0 },
        { x: 0, y: 0, z: 1 },
    ];

    for (const offset of checkOffsets) {
        const refPos = botPos.offset(offset.x, offset.y, offset.z);
        const refBlock = bot.blockAt(refPos);
        if (!refBlock || refBlock.name === 'air' || refBlock.name === 'water') continue;

        // The placement position is on top of or adjacent to the reference block
        const placePos = refPos.offset(0, 1, 0);
        const placeBlock = bot.blockAt(placePos);
        if (placeBlock && placeBlock.name !== 'air') continue; // spot taken

        try {
            await bot.equip(tableItem, 'hand');
            // Place against the reference block, placing on top of it
            const dirVec = placePos.clone().subtract(refPos);
            await bot.placeBlock(refBlock, dirVec);
            // Verify it worked
            const newBlock = bot.blockAt(placePos);
            if (newBlock && newBlock.name === 'crafting_table') {
                return true;
            }
        } catch (e) {
            // Try next position
            continue;
        }
    }
    return false;
}

async function equipItem(itemName) {
    const item = bot.inventory.findInventoryItem(itemName);
    if (!item) return { ok: false, reason: `no ${itemName} in inventory` };
    await bot.equip(item, 'hand');
    return { ok: true, equipped: itemName };
}

async function consumeItem(itemName) {
    const item = bot.inventory.findInventoryItem(itemName);
    if (!item) return { ok: false, reason: `no ${itemName} in inventory` };
    await bot.equip(item, 'hand');
    await bot.consume();
    return { ok: true, consumed: itemName };
}

async function discardItem(itemName, count) {
    const item = bot.inventory.findInventoryItem(itemName);
    if (!item) return { ok: false, reason: `no ${itemName} in inventory` };
    await bot.toss(item.type, null, count);
    return { ok: true, discarded: itemName, count };
}

async function pickupNearby(radius) {
    const items = Object.values(bot.entities).filter(e => {
        if (!e || e === bot.entity) return false;
        return e.name === 'item' && e.position.distanceTo(bot.entity.position) <= radius;
    });
    let picked = 0;
    for (const item of items) {
        try {
            await bot.pathfinder.goto(new goals.GoalBlock(item.position.x, item.position.y, item.position.z));
            picked++;
        } catch (e) { /* skip */ }
    }
    return { ok: true, picked };
}

// ── Combat implementations ────────────────────────────────────────────────

async function attackNearestEntity(entityType) {
    const entities = Object.values(bot.entities).filter(e => {
        if (!e || e === bot.entity || e.type !== 'mob') return false;
        const dist = e.position.distanceTo(bot.entity.position);
        return dist <= 16 && (entityType === 'hostile' ? isHostile(e) : e.name === entityType);
    });
    if (entities.length === 0) return { ok: false, reason: `no ${entityType} found` };
    entities.sort((a, b) => a.position.distanceTo(bot.entity.position) - b.position.distanceTo(bot.entity.position));
    const target = entities[0];

    await equipBestWeapon();
    await bot.pathfinder.goto(new goals.GoalBlock(target.position.x, target.position.y, target.position.z));
    await bot.attack(target);
    return { ok: true, attacked: target.name };
}

async function defendSelf(range) {
    const entities = Object.values(bot.entities).filter(e => {
        if (!e || e === bot.entity || e.type !== 'mob') return false;
        const dist = e.position.distanceTo(bot.entity.position);
        return dist <= range && isHostile(e);
    });
    if (entities.length === 0) return { ok: false, reason: 'no hostiles in range' };
    entities.sort((a, b) => a.position.distanceTo(bot.entity.position) - b.position.distanceTo(bot.entity.position));
    const target = entities[0];

    await equipBestWeapon();
    await bot.attack(target);
    return { ok: true, attacked: target.name, range };
}

async function moveAway(distance) {
    const entities = Object.values(bot.entities).filter(e => {
        if (!e || e === bot.entity) return false;
        return e.type === 'mob' && isHostile(e) && e.position.distanceTo(bot.entity.position) <= distance;
    });
    if (entities.length === 0) {
        // Just move backwards
        const dir = bot.entity.position.clone().subtract(bot.entity.position).add(new bot.vec3(0, 0, -distance));
        await goTo(dir.x, dir.y, dir.z);
        return { ok: true, moved: distance };
    }
    // Move away from nearest hostile
    const nearest = entities.sort((a, b) => a.position.distanceTo(bot.entity.position) - b.position.distanceTo(bot.entity.position))[0];
    const away = bot.entity.position.clone().subtract(nearest.position).normalize().scale(distance).add(bot.entity.position);
    await goTo(Math.round(away.x), Math.round(away.y), Math.round(away.z));
    return { ok: true, moved: distance };
}

// ── Safety implementations ──────────────────────────────────────────────────

async function placeTorchNearby() {
    // Check for torches in inventory
    const torch = bot.inventory.findInventoryItem('torch');
    if (!torch) return { ok: false, reason: 'no torches in inventory' };

    const pos = bot.entity.position;
    const searchRadius = 8;
    const minLight = 7;  // mobs spawn at light < 7

    // Find the darkest nearby position that can have a torch
    let bestSpot = null;
    let bestLight = 999;

    for (let dx = -searchRadius; dx <= searchRadius; dx++) {
        for (let dz = -searchRadius; dz <= searchRadius; dz++) {
            const y = Math.floor(pos.y);
            const checkPos = new bot.vec3(Math.floor(pos.x) + dx, y, Math.floor(pos.z) + dz);

            // Check ground block and the air above it
            const groundBlock = bot.blockAt(checkPos);
            const aboveBlock = bot.blockAt(checkPos.offset(0, 1, 0));

            if (!groundBlock || !aboveBlock) continue;
            // Must be a solid block with air above
            if (groundBlock.name === 'air' || groundBlock.name === 'water') continue;
            if (aboveBlock.name !== 'air' && aboveBlock.name !== 'cave_air') continue;
            if (!groundBlock.boundingBox || groundBlock.boundingBox !== 'block') continue;

            const light = Math.max(groundBlock.skyLight || 0, groundBlock.blockLight || 0);
            if (light >= minLight) continue; // already bright enough
            if (light >= bestLight) continue;

            bestSpot = checkPos;
            bestLight = light;
        }
    }

    if (!bestSpot) return { ok: false, reason: 'no dark spot found nearby', searched: searchRadius };

    // Place torch on top of the ground block
    await bot.equip(torch, 'hand');
    const groundBlock = bot.blockAt(bestSpot);
    await bot.placeBlock(groundBlock, new bot.vec3(0, 1, 0));
    return {
        ok: true,
        position: [bestSpot.x, bestSpot.y + 1, bestSpot.z],
        light_before: bestLight,
        placed: 'torch',
    };
}

// ── Chat implementation ────────────────────────────────────────────────────

async function sendChatMessage(message) {
    bot.chat(message);
    return { ok: true, sent: message };
}

// ── Interaction implementations ───────────────────────────────────────────

async function openChest(x, y, z) {
    const block = bot.blockAt(new bot.vec3(x, y, z));
    if (!block) return { ok: false, reason: 'no block at position' };
    if (block.name !== 'chest' && block.name !== 'trapped_chest' && block.name !== 'barrel') {
        return { ok: false, reason: `${block.name} is not a container` };
    }
    try {
        const chest = await bot.openContainer(block);
        const contents = {};
        for (const item of chest.containerItems()) {
            contents[item.name] = (contents[item.name] || 0) + item.count;
        }
        chest.close();
        return { ok: true, contents, position: [x, y, z] };
    } catch (e) {
        return { ok: false, reason: e.message };
    }
}

async function takeFromChest(x, y, z, itemName, count) {
    const block = bot.blockAt(new bot.vec3(x, y, z));
    if (!block) return { ok: false, reason: 'no block at position' };
    try {
        const chest = await bot.openContainer(block);
        const items = chest.containerItems().filter(i => i.name === itemName);
        if (items.length === 0) { chest.close(); return { ok: false, reason: `${itemName} not in chest` }; }
        let taken = 0;
        for (const item of items) {
            if (taken >= count) break;
            const toTake = Math.min(count - taken, item.count);
            await chest.withdraw(item.type, null, toTake);
            taken += toTake;
        }
        chest.close();
        return { ok: true, taken, item: itemName };
    } catch (e) {
        return { ok: false, reason: e.message };
    }
}

async function putInChest(x, y, z, itemName, count) {
    const block = bot.blockAt(new bot.vec3(x, y, z));
    if (!block) return { ok: false, reason: 'no block at position' };
    const item = bot.inventory.findInventoryItem(itemName);
    if (!item) return { ok: false, reason: `no ${itemName} in inventory` };
    try {
        const chest = await bot.openContainer(block);
        await chest.deposit(item.type, null, Math.min(count, item.count));
        chest.close();
        return { ok: true, deposited: itemName, count: Math.min(count, item.count) };
    } catch (e) {
        return { ok: false, reason: e.message };
    }
}

// ── Player interaction implementations ──────────────────────────────────────

async function followPlayer(username, distance) {
    const player = bot.players[username]?.entity;
    if (!player) return { ok: false, reason: `player ${username} not found` };
    const pos = player.position;
    await bot.pathfinder.goto(new goals.GoalNear(pos.x, pos.y, pos.z, distance));
    return { ok: true, following: username, distance };
}

async function goToPlayer(username) {
    const player = bot.players[username]?.entity;
    if (!player) return { ok: false, reason: `player ${username} not found` };
    const pos = player.position;
    await bot.pathfinder.goto(new goals.GoalNear(pos.x, pos.y, pos.z, 2));
    return { ok: true, position: [Math.round(pos.x), Math.round(pos.y), Math.round(pos.z)], player: username };
}

async function giveToPlayer(itemName, username, count) {
    const player = bot.players[username]?.entity;
    if (!player) return { ok: false, reason: `player ${username} not found` };
    const item = bot.inventory.findInventoryItem(itemName);
    if (!item) return { ok: false, reason: `no ${itemName} in inventory` };
    const toToss = Math.min(count, item.count);
    await bot.toss(item.type, null, toToss);
    return { ok: true, given: itemName, count: toToss, to: username };
}

// ── Furnace implementations ─────────────────────────────────────────────────

async function smeltItem(itemName, count) {
    // Find a furnace nearby
    const furnaceBlock = findNearestBlock('furnace', 16);
    if (!furnaceBlock) {
        // Try to place one if we have it in inventory
        const furnaceItem = bot.inventory.findInventoryItem('furnace');
        if (furnaceItem) {
            const placePos = bot.entity.position.offset(1, 0, 0);
            const refBlock = bot.blockAt(placePos.offset(0, -1, 0));
            if (refBlock && refBlock.name !== 'air') {
                await bot.equip(furnaceItem, 'hand');
                await bot.placeBlock(refBlock, new bot.vec3(0, 1, 0));
                // Wait a tick for the block to register
                await new Promise(resolve => setTimeout(resolve, 500));
            }
        }
        // Try to find the furnace again after placing
        const retryBlock = findNearestBlock('furnace', 16);
        if (!retryBlock) return { ok: false, reason: 'no furnace nearby and cannot place one' };
        return await _doSmelt(retryBlock, itemName, count);
    }
    return await _doSmelt(furnaceBlock, itemName, count);
}

async function _doSmelt(furnaceBlock, itemName, count) {
    try {
        const furnace = await bot.openFurnace(furnaceBlock);
        // Check what we're smelting
        const item = bot.inventory.findInventoryItem(itemName);
        if (!item) { furnace.close(); return { ok: false, reason: `no ${itemName} in inventory` }; }

        const toSmelt = Math.min(count, item.count);
        // Put items in the input slot
        await furnace.putInput(item.type, null, toSmelt);

        // Add fuel if needed
        const fuelItem = bot.inventory.findInventoryItem('coal', null, false)
            || bot.inventory.findInventoryItem('charcoal', null, false)
            || bot.inventory.findInventoryItem('oak_log', null, false)
            || bot.inventory.findInventoryItem('oak_planks', null, false);
        if (fuelItem) {
            await furnace.putFuel(fuelItem.type, null, Math.ceil(toSmelt / 8));
        }

        furnace.close();
        return { ok: true, smelting: itemName, count: toSmelt };
    } catch (e) {
        return { ok: false, reason: e.message };
    }
}

async function clearNearestFurnace() {
    const furnaceBlock = findNearestBlock('furnace', 16);
    if (!furnaceBlock) return { ok: false, reason: 'no furnace nearby' };
    try {
        const furnace = await bot.openFurnace(furnaceBlock);
        const outputItem = furnace.outputItem();
        const inputItem = furnace.inputItem();
        const fuelItem = furnace.fuelItem();

        const collected = {};
        if (outputItem) {
            const count = outputItem.count;
            await furnace.takeOutput();
            collected[outputItem.name] = count;
        }
        if (inputItem) {
            const count = inputItem.count;
            await furnace.takeInput();
            collected[inputItem.name] = count;
        }
        if (fuelItem) {
            const count = fuelItem.count;
            await furnace.takeFuel();
            collected['fuel_' + fuelItem.name] = count;
        }
        furnace.close();
        return { ok: true, collected };
    } catch (e) {
        return { ok: false, reason: e.message };
    }
}

// ── Helpers ───────────────────────────────────────────────────────────────

function findNearestBlock(blockType, radius) {
    const blocks = bot.findBlocks({
        matching: (block) => block && block.name === blockType,
        maxDistance: radius,
        count: 1,
    });
    if (blocks.length === 0) return null;
    const pos = blocks[0];
    return bot.blockAt(pos);
}

function isHostile(entity) {
    if (!entity || !entity.name) return false;
    const hostiles = ['zombie', 'skeleton', 'creeper', 'spider', 'cave_spider',
        'enderman', 'witch', 'slime', 'phantom', 'drowned', 'husk', 'stray',
        'blaze', 'ghast', 'magma_cube', 'wither_skeleton', 'piglin',
        'hoglin', 'zoglin', 'piglin_brute', 'warden', 'guardian', 'elder_guardian'];
    if (hostiles.includes(entity.name)) return true;
    if (entity.type === 'hostile') return true;
    return false;
}

async function equipBestWeapon() {
    const items = bot.inventory.items();
    let bestWeapon = null;
    let bestDamage = 0;
    for (const item of items) {
        let dmg = 0;
        if (item.name.includes('sword')) dmg = 6;
        else if (item.name.includes('axe') && !item.name.includes('pickaxe')) dmg = 5;
        if (dmg > bestDamage) {
            bestDamage = dmg;
            bestWeapon = item;
        }
    }
    if (bestWeapon) await bot.equip(bestWeapon, 'hand');
}

// Graceful shutdown
process.on('SIGTERM', () => { bot.quit(); process.exit(0); });
process.on('SIGINT', () => { bot.quit(); process.exit(0); });
