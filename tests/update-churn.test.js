// Usage updates that only bump a record's updatedAt must not rebuild the panel,
// and finishing an update must still schedule sync and the limits retry.
// Ported from Omarchy's test/shell.d/agents-panel-test.sh (#20401): the
// functions are lifted out of the QML and run as plain JavaScript.
const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const root = path.join(__dirname, '..')
const lift = (file, name) => {
  const source = fs.readFileSync(path.join(root, file), 'utf8')
  const match = source.match(new RegExp('function ' + name + '\\([^)]*\\) \\{[\\s\\S]*?\\n  \\}'))
  assert.ok(match, name + ' found in ' + file)
  return match[0]
}

test('Agent.parse ignores updatedAt-only rewrites', () => {
  let recordWrites = 0
  let storedRecord = null
  const agentRoot = {
    path: '/tmp/claude.json',
    parsedText: '',
    get record() { return storedRecord },
    set record(v) { recordWrites++; storedRecord = v }
  }
  agentRoot.clear = new Function('root', lift('Agent.qml', 'clear') + '\nreturn clear')(agentRoot)
  const parse = new Function('root', 'console', lift('Agent.qml', 'parse') + '\nreturn parse')(agentRoot, { warn() {} })

  const base = { id: 'claude', name: 'Claude', todayPrompts: 3, updatedAt: '2026-11-27T11:00:00+00:00' }
  parse(JSON.stringify(base))
  assert.equal(recordWrites, 1, 'the first parse sets the record')
  assert.equal(agentRoot.record.todayPrompts, 3)

  const first = agentRoot.record
  parse(JSON.stringify({ ...base, updatedAt: '2026-11-27T11:05:00+00:00' }))
  assert.equal(recordWrites, 1, 'an updatedAt-only rewrite leaves the record alone')
  assert.equal(agentRoot.record, first)

  // update-agy.py writes its records indented.
  parse(JSON.stringify({ ...base, updatedAt: '2026-11-27T11:10:00+00:00' }, null, 2))
  assert.equal(recordWrites, 2, 'a reformatted file is a change')
  parse(JSON.stringify({ ...base, updatedAt: '2026-11-27T11:15:00+00:00' }, null, 2))
  assert.equal(recordWrites, 2, 'an indented updatedAt-only rewrite leaves the record alone')

  parse(JSON.stringify({ ...base, todayPrompts: 4 }))
  assert.equal(recordWrites, 3, 'a real change updates the record')
  assert.equal(agentRoot.record.todayPrompts, 4)

  parse('{bad json')
  assert.equal(agentRoot.record, null, 'malformed JSON clears the record')
  assert.equal(agentRoot.parsedText, '')
})

test('Main.finishUpdate schedules sync and the limits retry', () => {
  const calls = []
  const deferred = []
  const state = {
    pendingUpdateKind: '',
    rescanAgents() { calls.push('rescan') },
    reloadRecords() { calls.push('reload') },
    scheduleLimitsRetry() { calls.push('retry') },
    scheduleSync() { calls.push('sync') },
    runUpdate(kind) { calls.push('run:' + kind) },
    Qt: { callLater(fn) { deferred.push(fn) } }
  }
  const finishUpdate = new Function('with (this) { ' + lift('Main.qml', 'finishUpdate') + '\nreturn finishUpdate }').call(state)

  finishUpdate()
  assert.deepEqual(calls, ['rescan', 'reload'], 'records reload before the deferred hooks')
  assert.equal(deferred.length, 1)
  deferred.shift()()
  assert.deepEqual(calls, ['rescan', 'reload', 'retry', 'sync'])

  calls.length = 0
  state.pendingUpdateKind = 'force'
  finishUpdate()
  deferred.shift()()
  assert.deepEqual(calls, ['rescan', 'reload', 'run:force', 'retry', 'sync'], 'a queued update still runs')
  assert.equal(state.pendingUpdateKind, '')
})
