import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { Hero } from "../src/sections/Hero";
import { LoadRun } from "../src/sections/LoadRun";
import { Footer } from "../src/sections/Footer";
import { WorldProvider, useWorld } from "../src/sim/WorldProvider";
import { SIMULATION_CONFIG } from "../src/demo";

test("the rendered workload settings configure the actual browser world", () => {
  const previous = { ...SIMULATION_CONFIG };
  Object.assign(SIMULATION_CONFIG, { drivers: 5, ttlSeconds: 4, ratePerSecond: 2, durationS: 3 });
  function WorldProbe() {
    const { world } = useWorld();
    const scheduled = world.scheduleLoad(SIMULATION_CONFIG.ratePerSecond, SIMULATION_CONFIG.durationS);
    return <output>{world.drivers.length} drivers, {world.ttlSeconds} s TTL, {scheduled} rides scheduled</output>;
  }
  try {
    const html = renderToStaticMarkup(<WorldProvider><WorldProbe /></WorldProvider>);
    assert.equal(html, "<output>5 drivers, 4 s TTL, 6 rides scheduled</output>");
  } finally {
    Object.assign(SIMULATION_CONFIG, previous);
  }
});

test("the headline presents configured traffic, not an unverified backend benchmark", () => {
  const html = renderToStaticMarkup(<WorldProvider><Hero /></WorldProvider>);
  assert.match(html, /aria-label="Simulation configuration"/);
  assert.doesNotMatch(html, /matches per minute|match latency p50|>p95</i);
  assert.doesNotMatch(html, /Headline figures are from/);
});

test("load results identify the browser model and do not compare it to an undocumented measured run", () => {
  const html = renderToStaticMarkup(<WorldProvider><LoadRun /></WorldProvider>);
  assert.match(html, /aria-label="Modeled browser load results"/);
  assert.match(html, /modeled latency/i);
  assert.doesNotMatch(html, /<td[^>]*>601|<td[^>]*>586/);
  assert.doesNotMatch(html, /59\s*\/\s*101 ms|62\s*\/\s*1101 ms/);
  assert.doesNotMatch(html, /compared with the measured demo/);
});

test("historical source links carry an adjacent unverified provenance warning", () => {
  const html = renderToStaticMarkup(<WorldProvider><LoadRun /></WorldProvider>);
  assert.match(html, /Historical, unverified/);
  assert.match(html, /raw output.*run timestamp.*machine metadata/i);
  assert.match(html, /https:\/\/github\.com\/SAY-5\/rideloop\/blob\/1945cbd8fee7cc428ac63a65931e120592c37ac3\/README.md/);
  assert.match(html, /https:\/\/github\.com\/SAY-5\/rideloop\/blob\/905549cfaa0daa1b58f920e84c61b1cfa725cbb8\/README.md/);
});

test("footer does not recast the simulation or historical transcript as a measured benchmark", () => {
  const html = renderToStaticMarkup(<Footer />);
  assert.match(html, /modeled/i);
  assert.doesNotMatch(html, /numbers are from the measured run|line-for-line ports/);
});
