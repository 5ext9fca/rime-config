-- 个人偏好：Ctrl+Space 切换、提交无分隔符拼音、按最近可见字符选择标点。
-- 不读取应用文档或剪贴板；鼠标移动/粘贴前的真实光标上下文无法保证。
local M = {}
local accepted, noop = 1, 2
local punctuation = { [","]=true, ["."]=true, [";"]=true, [":"]=true,
  ["!"]=true, ["?"]=true, ["("]=true, [")"]=true, ["["]=true,
  ["]"]=true, ["{"]=true, ["}"]=true, ["<"]=true, [">"]=true,
  ["\""]=true, ["'"]=true }
local navigation = { ["Left"]=true, ["Right"]=true, ["Up"]=true,
  ["Down"]=true, ["Home"]=true, ["End"]=true, ["BackSpace"]=true,
  ["Delete"]=true, ["Return"]=true, ["Tab"]=true, ["Escape"]=true }

local function commit_code(context, engine)
  if not context:is_composing() then return end
  local text = context.input:gsub("[%s']", "")
  context:clear()
  if text ~= "" then engine:commit_text(text) end
end

local function is_latin_tail(text)
  if not text or text == "" then return nil end
  local offset = utf8.offset(text, -1)
  if not offset then return nil end
  local last = text:sub(offset)
  local code = utf8.codepoint(last)
  if code >= 0x3400 and code <= 0x9fff
      or code >= 0x20000 and code <= 0x323af
      or code >= 0x3000 and code <= 0x303f
      or code >= 0xff00 and code <= 0xffef then
    return false
  end
  if last:match("^[%w%p]$") then return true end
  return nil
end

function M.init(env)
  local context = env.engine.context
  env.ignore_history = false
  -- 鼠须管只负责中文；macOS 的 Ctrl+Space 由系统切换输入源。
  env.chinese_only = rime_api and rime_api.get_distribution_code_name
      and rime_api.get_distribution_code_name() == "Squirrel" or false
  -- 其他前端切到英文时，提交去掉分隔符的拼音。
  env.option_connection = context.option_update_notifier:connect(function(ctx, name)
    if name == "ascii_mode" and ctx:get_option("ascii_mode") then
      if env.chinese_only then
        ctx:set_option("ascii_mode", false)
      else
        commit_code(ctx, env.engine)
      end
    end
  end)
  if env.chinese_only then context:set_option("ascii_mode", false) end
  env.commit_connection = context.commit_notifier:connect(function()
    env.ignore_history = false
  end)
end

function M.fini(env)
  if env.option_connection then env.option_connection:disconnect() end
  if env.commit_connection then env.commit_connection:disconnect() end
end

function M.func(key, env)
  if key:release() then return noop end
  local context = env.engine.context
  local repr = key:repr()
  if repr == "Control+space" then
    if env.chinese_only then return noop end
    commit_code(context, env.engine)
    context:set_option("ascii_mode", not context:get_option("ascii_mode"))
    return accepted
  end
  if key:ctrl() or key:alt() or key:super() then
    -- 快捷键可能移动光标或粘贴；不继续信任旧提交记录。
    env.ignore_history = true
    return noop
  end
  if navigation[repr] and not context:is_composing() then
    env.ignore_history = true
    return noop
  end
  if context:get_option("ascii_mode") then
    -- 英文模式下直接键入的字符可由 Rime commit_history 记录。
    if key.keycode >= 0x21 and key.keycode <= 0x7e then
      env.ignore_history = false
    end
    return noop
  end
  if key.keycode < 0x21 or key.keycode > 0x7e then return noop end
  local char = string.char(key.keycode)
  if not punctuation[char] then return noop end
  -- 单引号在拼音串内仍作为分隔符；中括号在有候选时保留以词定字。
  if context:is_composing() and (char == "'" or char == "[" or char == "]") then return noop end
  local text
  if context:is_composing() then
    text = context:get_commit_text()
  elseif not env.ignore_history and context.commit_history then
    local last = context.commit_history:back()
    text = last and last.text
  end
  local latin = is_latin_tail(text)
  -- 无可靠上下文时回退到当前中文模式的中文标点。
  context:set_option("ascii_punct", latin == true)
  if latin then
    if context:is_composing() then context:commit() end
    env.engine:commit_text(char)
    return accepted
  end
  -- 中文标点交给原生 punctuator，保留配对引号等行为。
  return noop
end

return M
