async function renderActivePlan() {
  const res = await fetch('/assessment/api/floor_plans');
  const data = await res.json();
  const active = (data.plans || []).find((p) => p.is_active) || (data.plans || [])[0];
  const target = document.getElementById('activePlan');
  if (!active) {
    target.innerHTML = '<div class="card-body text-muted">Kein Lageplan vorhanden.</div>';
    return;
  }
  target.innerHTML = `
    <img src="${active.image_path}" class="card-img-top" alt="${active.name}">
    <div class="card-body">
      <h2 class="h6 mb-0">${active.name}</h2>
    </div>
  `;
}

renderActivePlan();
