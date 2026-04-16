async function loadPlans() {
  const res = await fetch('/assessment/api/floor_plans');
  const data = await res.json();
  const container = document.getElementById('plans');
  container.innerHTML = (data.plans || []).map((plan) => `
    <div class="col-md-4">
      <div class="card h-100">
        <img src="${plan.image_path}" class="card-img-top" alt="${plan.name}">
        <div class="card-body">
          <h2 class="h6">${plan.name}</h2>
          <div class="d-flex gap-2">
            <button class="btn btn-sm btn-outline-primary" onclick="setActive(${plan.id})">Aktivieren</button>
            <button class="btn btn-sm btn-outline-danger" onclick="deletePlan(${plan.id})">Löschen</button>
          </div>
        </div>
      </div>
    </div>
  `).join('');
}

async function setActive(id) {
  await fetch('/assessment/api/floor_plans', {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({id, is_active: true})
  });
  loadPlans();
}

async function deletePlan(id) {
  await fetch('/assessment/api/floor_plans', {
    method: 'DELETE',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({id})
  });
  loadPlans();
}

document.getElementById('uploadForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const uploadRes = await fetch('/assessment/api/upload_floor_plan', { method: 'POST', body: fd });
  const uploadData = await uploadRes.json();
  if (!uploadData.success) return;
  await fetch('/assessment/api/floor_plans', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: fd.get('name'), image_path: uploadData.image_path})
  });
  e.target.reset();
  loadPlans();
});

loadPlans();
