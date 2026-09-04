/* ============================================
   Ganfeng Fiberglass · 智能客服浮窗
   基于 RAG 的轻量版本，可由后端 /api/chat 驱动
   ============================================ */
(function(){
'use strict';

const SESSION_ID = (function(){
  return (Math.random().toString(36).slice(2, 6) + Math.random().toString(36).slice(2, 6)).slice(0, 12);
})();

function appendMessage(role, content, intent){
  const box = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.className = 'msg msg-' + role;
  // 把 markdown-lite 转换（**bold** + - list + line breaks）
  const html = content
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br>');
  div.innerHTML = `<div class="msg-content">${html}${intent && intent !== 'general' ? `<div style="margin-top:6px;font-size:10px;color:#94a3b8">intent: ${intent}</div>` : ''}</div>`;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

async function sendChat(text){
  appendMessage('user', text);
  // 临时"正在输入"指示
  const typing = document.createElement('div');
  typing.className = 'msg msg-bot';
  typing.id = 'typing-indicator';
  const typingText = (window.GF_I18N && window.GF_CURRENT_LANG)
    ? window.GF_I18N[window.GF_CURRENT_LANG()].chatTyping
    : 'AI is typing...';
  typing.innerHTML = '<div class="msg-content"><em>' + typingText + '</em></div>';
  document.getElementById('chat-messages').appendChild(typing);

  try{
    const lang = (window.GF_CURRENT_LANG ? window.GF_CURRENT_LANG() : 'en');
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ message: text, session_id: SESSION_ID, lang: lang }),
    });
    const data = await res.json();
    document.getElementById('typing-indicator').remove();
    if (data.reply){
      appendMessage('bot', data.reply.text, data.reply.intent);
    }
  } catch(err){
    document.getElementById('typing-indicator').remove();
    appendMessage('bot', '⚠️ 服务暂时不可用，请稍后再试或拨打 WhatsApp +86-1380-xxx-xxx');
  }
}

const form = document.getElementById('chat-form');
if (form){
  form.addEventListener('submit', e => {
    e.preventDefault();
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    sendChat(text);
  });
}

})();
