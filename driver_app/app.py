function startSession(existingSession = null) {
  let plate, name, lineId, color, startTime;

  if (existingSession) {
    // If we are resuming after a refresh
    ({plate, name, lineId, color, startTime} = existingSession);
  } else {
    // New login
    plate = document.getElementById('inp-plate').value.trim().toUpperCase();
    name = document.getElementById('inp-name').value.trim();
    lineId = document.getElementById('sel-line').value;
    color = COLORS[lineId] || '#00d4ff';
    startTime = Date.now();
  }

  session = {plate, name, lineId, color, startTime};
  
  // SAVE TO BROWSER MEMORY
  localStorage.setItem('bus_session', JSON.stringify(session));

  document.getElementById('login-screen').style.display = 'none';
  document.getElementById('status-bar').style.display = 'flex';
  document.getElementById('stats-strip').style.display = 'flex';
  document.getElementById('recenter-btn').style.display = 'flex';
  document.getElementById('s-name').textContent = plate + ' · ' + name;
  
  timerInt = setInterval(tickTimer, 1000);
  watchId = navigator.geolocation.watchPosition(onGPS, null, {enableHighAccuracy:true});
}
