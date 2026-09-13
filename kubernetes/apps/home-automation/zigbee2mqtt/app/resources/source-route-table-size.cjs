"use strict";

// Legrand mains routers never emit a Route Record and strip themselves from the ones they
// relay, so the coordinator's source routes to anything at or behind one go stale and are
// never corrected -- it then acks a remote through a router that dropped it as a child.
// A source route table of zero forces the stack onto AODV, which Legrand does answer and
// which route errors repair. zigbee-herdsman exposes no knob for this config value.

const CONFIG_ID_SOURCE_ROUTE_TABLE_SIZE = 0x1a;

const size = Number.parseInt(process.env.EMBER_SOURCE_ROUTE_TABLE_SIZE ?? "0", 10);

if (!Number.isInteger(size) || size < 0 || size > 255) {
    throw new Error(`[source-route-patch] EMBER_SOURCE_ROUTE_TABLE_SIZE must be 0-255, got ${process.env.EMBER_SOURCE_ROUTE_TABLE_SIZE}`);
}

// Resolving and patching at preload time keeps the CommonJS module instance shared with the
// copy zigbee2mqtt later requires. Both throws below are deliberate: a silently inert patch
// would let the mesh regress on a version bump with nothing in the logs to say so.
const { Ezsp } = require(
    require.resolve("zigbee-herdsman/dist/adapter/ember/ezsp/ezsp.js", { paths: ["/app", process.cwd()] }),
);

if (typeof Ezsp?.prototype?.start !== "function" || typeof Ezsp?.prototype?.ezspSetConfigurationValue !== "function") {
    throw new Error("[source-route-patch] zigbee-herdsman Ezsp API changed, patch cannot apply");
}

// Resizing a table is only accepted before the stack comes up, which in initEzsp means
// before registerFixedEndpoints -- so this rides along with the first config value
// herdsman writes rather than picking a call site of its own. Anywhere later returns
// INVALID_STATE. The flag resets on start() so a reconnect reapplies it.
let pending = true;

const start = Ezsp.prototype.start;

Ezsp.prototype.start = async function (...args) {
    pending = true;

    return await start.apply(this, args);
};

const setConfigurationValue = Ezsp.prototype.ezspSetConfigurationValue;

Ezsp.prototype.ezspSetConfigurationValue = async function (configId, value) {
    if (pending && configId !== CONFIG_ID_SOURCE_ROUTE_TABLE_SIZE) {
        pending = false;

        const status = await setConfigurationValue.call(this, CONFIG_ID_SOURCE_ROUTE_TABLE_SIZE, size);

        console.log(`[source-route-patch] SOURCE_ROUTE_TABLE_SIZE=${size} status=${status} (0 is OK)`);
    }

    return await setConfigurationValue.call(this, configId, value);
};
