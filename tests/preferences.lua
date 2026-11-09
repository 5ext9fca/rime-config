local prefs = dofile('config/lua/hx_preferences.lua')
local function make()
  local function notifier()
    local n = { callbacks = {} }
    function n:connect(fn)
      table.insert(self.callbacks, fn)
      return {disconnect = function() end}
    end
    function n:emit(...)
      for _, fn in ipairs(self.callbacks) do fn(...) end
    end
    return n
  end
  local ctx = { input = '', options = {}, last = nil, preview = '' }
  ctx.option_update_notifier = notifier()
  ctx.commit_notifier = notifier()
  function ctx:is_composing() return self.input ~= '' end
  function ctx:clear() self.input = '' end
  function ctx:get_option(name) return self.options[name] == true end
  function ctx:set_option(name, value)
    self.options[name] = value
    self.option_update_notifier:emit(self, name)
  end
  function ctx:get_commit_text() return self.preview end
  ctx.commit_history = {back = function() return ctx.last and {text=ctx.last} end}
  local engine = {context=ctx, output={}}
  function engine:commit_text(text)
    table.insert(self.output, text)
    ctx.last = text
  end
  function ctx:commit()
    engine:commit_text(self.preview)
    self:clear()
    self.commit_notifier:emit(self)
  end
  local env = {engine=engine}
  prefs.init(env)
  return env, ctx, engine
end
local function key(repr, code, ctrl)
  return {keycode=code or string.byte(repr), repr=function() return repr end,
    release=function() return false end, ctrl=function() return ctrl or false end,
    alt=function() return false end, super=function() return false end}
end
local env, ctx, engine = make()
ctx.input = "xi'an hao"
assert(prefs.func(key('Control+space',32,true),env)==1)
assert(engine.output[1]=='xianhao' and ctx:get_option('ascii_mode') and ctx.input=='')
assert(prefs.func(key('Control+space',32,true),env)==1)
assert(not ctx:get_option('ascii_mode'))
assert(prefs.func(key('Shift_L',65505),env)==2 and not ctx:get_option('ascii_mode'))
ctx.input="ni'hao"
ctx:set_option('ascii_mode',true)
assert(engine.output[#engine.output]=='nihao' and ctx.input=='')
ctx:set_option('ascii_mode',false)
ctx.last='hello'
assert(prefs.func(key(',',44),env)==1 and engine.output[#engine.output]==',')
ctx.last='中文'
assert(prefs.func(key(',',44),env)==2 and not ctx:get_option('ascii_punct'))
ctx.last='42'
assert(prefs.func(key('.',46),env)==1 and engine.output[#engine.output]=='.')
ctx.input='abc'; ctx.preview='English'
assert(prefs.func(key('!',33),env)==1 and engine.output[#engine.output-1]=='English')
ctx.input='nihao'; ctx.preview='你好'
assert(prefs.func(key(',',44),env)==2 and not ctx:get_option('ascii_punct'))
assert(prefs.func(key("'",39),env)==2 and ctx.input=='nihao')
assert(prefs.func(key('minus',45),env)==2)
assert(prefs.func(key('equal',61),env)==2)
ctx:clear(); ctx.last='English'
prefs.func(key('Left',65361),env)
assert(prefs.func(key(',',44),env)==2 and not ctx:get_option('ascii_punct'))
ctx.last=nil; env.ignore_history=false
assert(prefs.func(key(',',44),env)==2 and not ctx:get_option('ascii_punct'))
prefs.fini(env)
print('Lua preference behavior tests passed')
