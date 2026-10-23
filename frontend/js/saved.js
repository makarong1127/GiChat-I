/* 기찾이 공용: 저장 버튼 상태/토글
 *
 * 사용법
 *   <script src="js/saved.js"></script>
 *   <button data-save-id="기사ID">저장</button>
 *   await GichatiSaved.load();          // 저장 ID 목록 불러오기 (쿠키 기준)
 *   GichatiSaved.bind(container);       // 컨테이너 안의 data-save-id 버튼들에 상태/클릭 연결
 *
 * 버튼 클릭 → POST/DELETE /api/saved/{id} → 버튼 모양 갱신.
 * 'gichati:saved-changed' 이벤트를 document 에 보내서 다른 영역(목록 등)이 반응할 수 있게 한다.
 */
window.GichatiSaved = (() => {
  let ids = null;

  const CLASS_SAVED =
    'bg-[#D8EEFF] text-[#2563EB] px-3.5 py-1 rounded-md text-xs font-medium hover:bg-[#C2E2FF] transition';
  const CLASS_UNSAVED =
    'border border-slate-200 text-slate-600 px-3 py-1 rounded-md text-xs hover:border-sky-400 hover:text-sky-600 hover:bg-sky-50 transition';

  async function load() {
    try {
      const res = await fetch('/api/saved/ids');
      const data = await res.json();
      ids = new Set(data.ids || []);
    } catch {
      ids = new Set();
    }
    return ids;
  }

  function has(id) {
    return !!ids && ids.has(id);
  }

  function paint(btn, saved) {
    const unsaveLabel = btn.dataset.unsaveLabel || '저장됨';
    const saveLabel = btn.dataset.saveLabel || '저장';
    btn.className = saved ? CLASS_SAVED : CLASS_UNSAVED;
    btn.textContent = saved ? unsaveLabel : saveLabel;
    btn.dataset.saved = saved ? '1' : '0';
  }

  async function toggle(id) {
    const saved = has(id);
    const res = await fetch(`/api/saved/${encodeURIComponent(id)}`, { method: saved ? 'DELETE' : 'POST' });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    if (!ids) ids = new Set();
    if (saved) ids.delete(id); else ids.add(id);
    document.dispatchEvent(new CustomEvent('gichati:saved-changed', { detail: { id, saved: !saved } }));
    return !saved;
  }

  function bind(root = document) {
    root.querySelectorAll('[data-save-id]').forEach((btn) => {
      const id = btn.dataset.saveId;
      paint(btn, has(id));
      btn.onclick = async (e) => {
        e.stopPropagation();
        e.preventDefault();
        btn.disabled = true;
        try {
          paint(btn, await toggle(id));
        } catch (err) {
          alert('저장에 실패했어요: ' + err.message);
        } finally {
          btn.disabled = false;
        }
      };
    });
  }

  return { load, has, bind, paint, toggle };
})();
