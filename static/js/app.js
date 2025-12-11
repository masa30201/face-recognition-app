// グローバル変数
let currentTab = 'upload';
let currentEditingPerson = null;
let statusInterval = null;

// 初期化
document.addEventListener('DOMContentLoaded', () => {
    checkAuthentication();
    setupEventListeners();
});

// 認証チェック
async function checkAuthentication() {
    try {
        const response = await fetch('/api/auth/check');
        const data = await response.json();
        
        if (data.authenticated) {
            showMainApp();
        }
    } catch (error) {
        console.error('Auth check error:', error);
    }
}

// イベントリスナー設定
function setupEventListeners() {
    // 認証
    document.getElementById('auth-submit-btn').addEventListener('click', authenticate);
    document.getElementById('passphrase-input').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') authenticate();
    });
    
    // タブ切り替え
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });
    
    // アップロード
    const uploadArea = document.getElementById('upload-area');
    const fileInput = document.getElementById('file-input');
    
    uploadArea.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', (e) => handleFileUpload(e.target.files));
    
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('dragover');
    });
    
    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('dragover');
    });
    
    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
        const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'));
        if (files.length > 0) handleFileUpload(files);
    });
    
    // 処理
    document.getElementById('start-process-btn').addEventListener('click', startProcessing);
    document.getElementById('refresh-status-btn').addEventListener('click', updateQueueStatus);
    
    // モーダル
    document.getElementById('save-person-btn').addEventListener('click', savePersonName);
    document.getElementById('cancel-person-btn').addEventListener('click', () => closeModal('edit-person-modal'));
}

// 認証
async function authenticate() {
    const passphrase = document.getElementById('passphrase-input').value;
    const errorDiv = document.getElementById('auth-error');
    
    try {
        const response = await fetch('/api/auth', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ passphrase })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showMainApp();
        } else {
            errorDiv.style.display = 'block';
            document.getElementById('passphrase-input').value = '';
            setTimeout(() => errorDiv.style.display = 'none', 3000);
        }
    } catch (error) {
        console.error('Auth error:', error);
        alert('認証エラーが発生しました');
    }
}

// メインアプリ表示
function showMainApp() {
    document.getElementById('auth-screen').style.display = 'none';
    document.getElementById('main-app').style.display = 'block';
    loadStatistics();
}

// タブ切り替え
function switchTab(tabName) {
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
    
    document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');
    document.getElementById(`${tabName}-tab`).classList.add('active');
    
    currentTab = tabName;
    
    if (tabName === 'persons') loadPersons();
    if (tabName === 'photos') loadPhotos();
    if (tabName === 'process') {
        updateQueueStatus();
        startStatusPolling();
    } else {
        stopStatusPolling();
    }
}

// ファイルアップロード
async function handleFileUpload(files) {
    const filesArray = Array.from(files);
    
    if (filesArray.length > 500) {
        alert('一度に最大500枚までアップロードできます');
        return;
    }
    
    const formData = new FormData();
    filesArray.forEach(file => formData.append('files', file));
    
    showUploadProgress(0, filesArray.length);
    
    try {
        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (data.success) {
            showUploadComplete(data.uploaded, filesArray.length);
            loadStatistics();
        } else {
            alert('アップロードエラー: ' + (data.error || '不明なエラー'));
        }
    } catch (error) {
        console.error('Upload error:', error);
        alert('アップロードエラーが発生しました');
    }
}

// アップロード進捗表示
function showUploadProgress(current, total) {
    const statusDiv = document.getElementById('upload-status');
    const progressBar = document.getElementById('upload-progress-bar');
    const statusText = document.getElementById('upload-status-text');
    
    statusDiv.style.display = 'block';
    statusDiv.classList.remove('success');
    
    const percentage = Math.round((current / total) * 100);
    progressBar.style.width = percentage + '%';
    progressBar.textContent = `${percentage}%`;
    statusText.textContent = `アップロード中: ${current} / ${total} 枚`;
}

// アップロード完了表示
function showUploadComplete(success, total) {
    const statusDiv = document.getElementById('upload-status');
    const progressBar = document.getElementById('upload-progress-bar');
    const statusText = document.getElementById('upload-status-text');
    
    statusDiv.classList.add('success');
    progressBar.style.width = '100%';
    progressBar.textContent = '完了!';
    statusText.textContent = `✓ ${success} / ${total} 枚のアップロードが完了しました`;
    
    setTimeout(() => statusDiv.style.display = 'none', 5000);
}

// 処理開始
async function startProcessing() {
    try {
        const response = await fetch('/api/process/start', { method: 'POST' });
        const data = await response.json();
        
        alert(data.message || `${data.count}枚の処理を開始しました`);
        updateQueueStatus();
        startStatusPolling();
    } catch (error) {
        console.error('Process error:', error);
        alert('処理開始エラー');
    }
}

// キュー状態更新
async function updateQueueStatus() {
    try {
        const response = await fetch('/api/queue/status');
        const data = await response.json();
        
        document.getElementById('queue-pending').textContent = data.pending;
        document.getElementById('queue-processing').textContent = data.processing;
        document.getElementById('queue-completed').textContent = data.completed;
        document.getElementById('queue-failed').textContent = data.failed;
        
        loadStatistics();
    } catch (error) {
        console.error('Queue status error:', error);
    }
}

// 状態ポーリング開始
function startStatusPolling() {
    if (statusInterval) clearInterval(statusInterval);
    statusInterval = setInterval(updateQueueStatus, 10000); // 10秒ごと
}

// 状態ポーリング停止
function stopStatusPolling() {
    if (statusInterval) {
        clearInterval(statusInterval);
        statusInterval = null;
    }
}

// 統計情報読み込み
async function loadStatistics() {
    try {
        const response = await fetch('/api/statistics');
        const data = await response.json();
        
        document.getElementById('uploaded-count').textContent = data.totalPhotos;
        document.getElementById('processed-count').textContent = data.processedPhotos;
        document.getElementById('total-persons').textContent = data.totalPersons;
        document.getElementById('total-faces').textContent = data.totalFaces;
    } catch (error) {
        console.error('Statistics error:', error);
    }
}

// 人物一覧読み込み
async function loadPersons() {
    try {
        const response = await fetch('/api/persons');
        const data = await response.json();
        
        const grid = document.getElementById('persons-grid');
        
        if (data.data.length === 0) {
            grid.innerHTML = '<div class="empty-state"><div class="empty-state-icon">👤</div><p class="empty-state-text">まだ人物が登録されていません</p></div>';
            return;
        }
        
        grid.innerHTML = data.data.map(person => `
            <div class="person-card" data-person-id="${person.id}">
                <img src="${person.thumbnail_url || ''}" alt="${person.name}" class="person-thumbnail" onerror="this.src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22%3E%3Crect fill=%22%23ccc%22 width=%22100%22 height=%22100%22/%3E%3Ctext x=%2250%22 y=%2250%22 text-anchor=%22middle%22 dy=%22.3em%22 font-size=%2240%22%3E%3F%3C/text%3E%3C/svg%3E'">
                <div class="person-name">${person.name}</div>
                <div class="person-count">${person.photo_count} 枚の写真</div>
            </div>
        `).join('');
        
        // クリックイベント
        grid.querySelectorAll('.person-card').forEach(card => {
            card.addEventListener('click', () => openEditPersonModal(card.dataset.personId));
        });
    } catch (error) {
        console.error('Load persons error:', error);
    }
}

// 写真一覧読み込み
async function loadPhotos() {
    try {
        const response = await fetch('/api/photos');
        const data = await response.json();
        
        const grid = document.getElementById('photos-grid');
        
        if (data.data.length === 0) {
            grid.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📷</div><p class="empty-state-text">写真がありません</p></div>';
            return;
        }
        
        grid.innerHTML = data.data.map(photo => `
            <div class="photo-card">
                <img src="${photo.url || ''}" alt="${photo.file_name}" class="photo-thumbnail">
                <div class="photo-info">
                    <div class="photo-name" title="${photo.file_name}">${photo.file_name}</div>
                    <div class="photo-faces">${photo.face_count} 人検出${photo.processed ? ' ✓' : ''}</div>
                </div>
            </div>
        `).join('');
    } catch (error) {
        console.error('Load photos error:', error);
    }
}

// 人物編集モーダルを開く
function openEditPersonModal(personId) {
    currentEditingPerson = personId;
    fetch(`/api/persons?page=1&limit=1000`)
        .then(res => res.json())
        .then(data => {
            const person = data.data.find(p => p.id === personId);
            if (person) {
                document.getElementById('person-name-input').value = person.name;
                document.getElementById('edit-person-modal').classList.add('active');
            }
        });
}

// 人物名保存
async function savePersonName() {
    const name = document.getElementById('person-name-input').value.trim();
    
    if (!name || !currentEditingPerson) return;
    
    try {
        await fetch(`/api/persons/${currentEditingPerson}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });
        
        closeModal('edit-person-modal');
        loadPersons();
    } catch (error) {
        console.error('Save person error:', error);
        alert('保存エラー');
    }
}

// モーダルを閉じる
function closeModal(modalId) {
    document.getElementById(modalId).classList.remove('active');
    currentEditingPerson = null;
}
