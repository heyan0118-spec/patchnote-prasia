/**
 * 프라시아 전기 패치노트 검색 대시보드
 */
const API_BASE = CONFIG.API_BASE;

const $form = document.getElementById('searchForm');
const $input = document.getElementById('questionInput');
const $btn = document.getElementById('searchBtn');
const $loading = document.getElementById('loading');
const $results = document.getElementById('results');
const $answerBox = document.getElementById('answerBox');
const $statusBar = document.getElementById('statusBar');
const $emptyState = document.getElementById('emptyState');
const $homeLink = document.getElementById('homeLink');
const $recentSearches = document.getElementById('recentSearches');
const $recentChips = document.getElementById('recentChips');

// 태그 한글화 맵
const TAG_MAP = {
  'class': '클래스',
  'balance': '밸런스',
  'event': '이벤트',
  'system': '시스템',
  'item': '아이템',
  'content': '콘텐츠',
  'world_open': '월드 오픈',
  'maintenance': '점검',
  'event_record': '이벤트 기록',
  'chunk': '패치 본문'
};

// 페이지 로드 시 최근 검색어 불러오기
document.addEventListener('DOMContentLoaded', () => {
  renderRecentSearches();
});

// 홈 링크 클릭 시 초기화
$homeLink.addEventListener('click', (e) => {
  e.preventDefault();
  resetToHome();
});

function resetToHome() {
  $input.value = '';
  $results.innerHTML = '';
  $answerBox.classList.remove('visible');
  $statusBar.innerHTML = '';
  $emptyState.style.display = 'block';
  renderRecentSearches();
}

// 최근 검색어 관리
function saveSearch(query) {
  if (!query) return;
  let history = JSON.parse(localStorage.getItem('search_history') || '[]');
  // 중복 제거 및 최신순 정렬
  history = [query, ...history.filter(q => q !== query)].slice(0, 10);
  localStorage.setItem('search_history', JSON.stringify(history));
}

function renderRecentSearches() {
  const history = JSON.parse(localStorage.getItem('search_history') || '[]');
  if (history.length > 0) {
    $recentSearches.style.display = 'block';
    $recentChips.innerHTML = history.map(q => 
      `<span class="example-chip recent-chip" data-q="${esc(q)}">${esc(q)}</span>`
    ).join('');
    
    // 이벤트 바인딩
    $recentChips.querySelectorAll('.recent-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        $input.value = chip.dataset.q;
        $form.dispatchEvent(new Event('submit'));
      });
    });
  } else {
    $recentSearches.style.display = 'none';
  }
}

// 검색 예시 칩 이벤트
document.querySelectorAll('.example-chip').forEach(chip => {
  if (!chip.classList.contains('recent-chip')) {
    chip.addEventListener('click', () => {
      $input.value = chip.dataset.q;
      $form.dispatchEvent(new Event('submit'));
    });
  }
});

$form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const question = $input.value.trim();
  if (!question) return;

  saveSearch(question);
  $btn.disabled = true;
  $loading.classList.add('active');
  $results.innerHTML = '';
  $answerBox.classList.remove('visible');
  $statusBar.innerHTML = '';
  $emptyState.style.display = 'none';

  try {
    const body = { question };
    const topic = document.getElementById('filterTopic').value;
    const dateFrom = document.getElementById('filterDateFrom').value;
    const dateTo = document.getElementById('filterDateTo').value;
    if (topic || dateFrom || dateTo) {
      body.filters = {};
      if (topic) body.filters.topic_type = topic;
      if (dateFrom) body.filters.date_from = dateFrom;
      if (dateTo) body.filters.date_to = dateTo;
    }

    const resp = await fetch(`${API_BASE}/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    renderResults(data);
  } catch (err) {
    $results.innerHTML = `<div class="empty-state"><p>오류가 발생했습니다: ${err.message}</p></div>`;
  } finally {
    $btn.disabled = false;
    $loading.classList.remove('active');
  }
});

function renderResults(data) {
  $answerBox.textContent = data.answer;
  $answerBox.classList.add('visible');

  const isHistory = data.policy_applied === 'preserve_history';
  const policyClass = isHistory ? 'policy-history' : 'policy-latest';
  const policyLabel = isHistory ? '이력 보존' : '최신 우선';
  $statusBar.innerHTML = `
    <span>${data.total_hits}건의 결과</span>
    <span class="policy-badge ${policyClass}">${policyLabel}</span>
  `;

  if (!data.evidence || data.evidence.length === 0) {
    $results.innerHTML = '<div class="empty-state"><p>관련 패치노트를 찾지 못했습니다.</p></div>';
    return;
  }

  if (isHistory) {
    renderHistoryView(data.evidence);
  } else {
    $results.innerHTML = `<div class="evidence-list">${renderCards(data.evidence)}</div>`;
  }
}

function renderHistoryView(evidence) {
  const tableHtml = buildTimelineTable(evidence);
  const cardsHtml = renderCards(evidence);

  $results.innerHTML = `
    <div class="view-toggle">
      <button class="active" data-view="timeline">타임라인</button>
      <button data-view="cards">상세 카드</button>
    </div>
    <div id="viewTimeline" class="timeline-section">${tableHtml}</div>
    <div id="viewCards" class="evidence-list" style="display:none">${cardsHtml}</div>
  `;

  $results.querySelectorAll('.view-toggle button').forEach(btn => {
    btn.addEventListener('click', () => {
      $results.querySelectorAll('.view-toggle button').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const show = btn.dataset.view;
      document.getElementById('viewTimeline').style.display = show === 'timeline' ? '' : 'none';
      document.getElementById('viewCards').style.display = show === 'cards' ? '' : 'none';
    });
  });
}

function calcDuration(start, end) {
  if (!start || !end) return '';
  const s = new Date(start), e = new Date(end);
  const days = Math.round((e - s) / 86400000);
  if (days <= 0) return '';
  return `${days}일`;
}

function formatDate(isoStr) {
  if (!isoStr) return '';
  return isoStr.split('T')[0];
}

function formatScope(scope) {
  if (!scope) return '-';
  if (typeof scope === 'string' && scope.startsWith('{')) {
    try {
      const parsed = JSON.parse(scope);
      return parsed.raw || scope;
    } catch (e) {
      return scope;
    }
  }
  return scope;
}

function formatTitle(ev) {
  let title = ev.event_title || ev.patch_title || '-';
  if (title.includes(':')) {
    const parts = title.split(':');
    if (parts[0].length < 20) {
      title = parts[0].trim();
    }
  }
  if (ev.start_at && (title.includes('클래스 체인지') || title.includes('이벤트'))) {
    const month = new Date(ev.start_at).getMonth() + 1;
    if (!title.includes(`(${month}월)`)) {
      title += ` (${month}월)`;
    }
  }
  return title;
}

function buildTimelineTable(evidence) {
  const rows = evidence.map(ev => {
    const scoreClass = ev.score >= 0.7 ? 'score-high' : ev.score >= 0.4 ? 'score-mid' : 'score-low';
    const start = formatDate(ev.start_at);
    const end = formatDate(ev.end_at);
    const period = start ? `${start}${end ? ' ~ ' + end : ' ~'}` : (formatDate(ev.published_at) || '-');
    const dur = calcDuration(ev.start_at, ev.end_at);
    const cleanTitle = formatTitle(ev);
    const titleHtml = `<a href="${esc(ev.url)}" target="_blank" rel="noopener" class="tl-link">${esc(cleanTitle)}</a>`;
    const scope = formatScope(ev.target_scope);

    return `<tr>
      <td class="tl-period">${esc(period)}</td>
      <td class="tl-duration">${dur}</td>
      <td class="tl-content">${titleHtml}</td>
      <td class="tl-scope">${esc(scope)}</td>
      <td><span class="tl-score ${scoreClass}">${(ev.score * 100).toFixed(0)}%</span></td>
    </tr>`;
  }).join('');

  return `<table class="timeline-table">
    <thead><tr>
      <th>기간</th><th>일수</th><th>내용</th><th>대상</th><th>관련도</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function renderCards(evidence) {
  return evidence.map(ev => {
    const scoreClass = ev.score >= 0.7 ? 'score-high' : ev.score >= 0.4 ? 'score-mid' : 'score-low';
    const scoreLabel = (ev.score * 100).toFixed(0) + '%';
    const cleanTitle = formatTitle(ev);

    let tags = '';
    if (ev.published_at) tags += `<span class="tag tag-date">${formatDate(ev.published_at)}</span>`;
    if (ev.topic_type) tags += `<span class="tag tag-type">${TAG_MAP[ev.topic_type] || ev.topic_type}</span>`;
    if (ev.event_type) tags += `<span class="tag tag-event">${TAG_MAP[ev.event_type] || ev.event_type}</span>`;
    tags += `<span class="tag tag-source">${TAG_MAP[ev.source_type] || ev.source_type}</span>`;

    let eventHtml = '';
    if (ev.source_type === 'event_record') {
      eventHtml = `<dl class="event-details">`;
      if (ev.event_title) {
        eventHtml += `<dt>이벤트</dt><dd><a href="${esc(ev.url)}" target="_blank" rel="noopener" style="color: inherit;">${esc(ev.event_title)}</a></dd>`;
      }
      if (ev.start_at) eventHtml += `<dt>시작</dt><dd>${formatDate(ev.start_at)}</dd>`;
      if (ev.end_at) eventHtml += `<dt>종료</dt><dd>${formatDate(ev.end_at)}</dd>`;
      if (ev.target_scope) eventHtml += `<dt>대상</dt><dd>${esc(formatScope(ev.target_scope))}</dd>`;
      if (ev.realm_scope) eventHtml += `<dt>서버</dt><dd>${esc(formatScope(ev.realm_scope))}</dd>`;
      eventHtml += `</dl>`;
    }

    return `
      <div class="evidence-card">
        <div class="evidence-header">
          <div class="evidence-title">
            <a href="${esc(ev.url)}" target="_blank" rel="noopener">${esc(cleanTitle)}</a>
          </div>
          <span class="evidence-score ${scoreClass}">${scoreLabel}</span>
        </div>
        <div class="evidence-meta">${tags}</div>
        <div class="evidence-text" onclick="this.classList.toggle('expanded')">${esc(ev.chunk_text)}</div>
        ${eventHtml}
      </div>`;
  }).join('');
}

function esc(str) {
  if (!str) return '';
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}
