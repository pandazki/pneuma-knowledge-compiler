import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { transformWithEsbuild } from "vite";

const api = `export const startCall = (...args) => globalThis.callHarness.startCall(...args);
export class CallSocket {
  constructor(user, id, onFrame, onStatus) {
    Object.assign(this, { id, onFrame, onStatus });
    globalThis.callHarness.sockets.push(this);
    queueMicrotask(() => onStatus('open'));
  }
  end() { this.ended = true; this.onFrame({type:'closed'}); return true; }
  close() { this.closed = true; this.onStatus('closed'); }
}`;
const apiUrl = `data:text/javascript;base64,${Buffer.from(api).toString('base64')}`;
const path = new URL('../src/lib/callSession.ts', import.meta.url);
const source = (await readFile(path, 'utf8')).replace('"./api"', JSON.stringify(apiUrl));
const built = await transformWithEsbuild(source, path.pathname, {loader:'ts',format:'esm',target:'es2022'});
const {CallSession} = await import(`data:text/javascript;base64,${Buffer.from(built.code).toString('base64')}`);

function deferred() { let resolve; const promise = new Promise(r => {resolve = r;}); return {promise,resolve}; }
function setup(getMic, startCall) {
  const events = []; const track = {stopped:false,stop(){this.stopped=true;}};
  globalThis.callHarness = {sockets:[], startCall};
  Object.defineProperty(globalThis, 'navigator', {configurable:true,value:{mediaDevices:{getUserMedia:()=>getMic(track)}}});
  globalThis.RTCPeerConnection = class {
    iceGatheringState = 'complete';
    addTrack() {}
    createDataChannel() {return {readyState:'open',send(){}};}
    async createOffer() {return {type:'offer',sdp:'synthetic'};}
    async setLocalDescription(offer) {this.localDescription=offer;}
    async setRemoteDescription() {}
    close() {this.closed=true;}
  };
  const session = new CallSession('synthetic-tenant','en',{onEvent:event=>events.push(event),onRemoteStream(){}});
  return {session,events,track};
}

test('cancelling microphone permission stops a late stream without starting a billed call', async () => {
  const mic = deferred(); let starts = 0;
  const {session,events,track} = setup(()=>mic.promise,()=>{starts++;});
  const pending = session.start(); session.hangUpNow();
  mic.resolve({getTracks:()=>[track]}); await pending;
  assert.equal(starts,0); assert.equal(track.stopped,true);
  assert.deepEqual(events.map(e=>e.type),['start','ended']);
});

test('a cancelled server negotiation closes a late call instead of reviving the UI', async () => {
  const started = deferred(); const requested = deferred();
  const {session,events,track} = setup(track=>Promise.resolve({getTracks:()=>[track]}),()=>{requested.resolve();return started.promise;});
  const pending = session.start(); await requested.promise; session.hangUpNow();
  started.resolve({call_id:'synthetic-late-call',session_id:'synthetic',sdp:'answer'});
  await pending; await Promise.resolve();
  assert.equal(track.stopped,true);
  assert.equal(events.at(-1).type,'ended');
  assert.equal(events.some(e=>e.type==='connected'),false);
  assert.equal(globalThis.callHarness.sockets[0].ended,true);
  assert.equal(globalThis.callHarness.sockets[0].closed,true);
});
