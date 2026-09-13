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

if (typeof Ezsp?.prototype?.ezspSetConcentrator !== "function" || typeof Ezsp?.prototype?.ezspSetConfigurationValue !== "function") {
    throw new Error("[source-route-patch] zigbee-herdsman Ezsp API changed, patch cannot apply");
}

// ezspSetConcentrator is the last call in initEzsp before the concentrator starts, so the
// config value lands alongside the ones herdsman sets itself and before any MTORR goes out.
const setConcentrator = Ezsp.prototype.ezspSetConcentrator;

Ezsp.prototype.ezspSetConcentrator = async function (...args) {
    const status = await this.ezspSetConfigurationValue(CONFIG_ID_SOURCE_ROUTE_TABLE_SIZE, size);

    console.log(`[source-route-patch] SOURCE_ROUTE_TABLE_SIZE=${size} status=${status} (0 is OK)`);

    return await setConcentrator.apply(this, args);
};
