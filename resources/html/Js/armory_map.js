// ArmoryGIS Map Controller (legacy standalone — main app uses map.html inline JS)
let map, tileLayer, markerLayer;
let pyBridge = null;
let targetMarker = null;

document.addEventListener('DOMContentLoaded', () => {
    map = L.map('map', {
        center: [31.5, 34.8],
        zoom: 6,
        dragging: true,
        scrollWheelZoom: true,
        doubleClickZoom: true,
        zoomControl: false,
    });

    L.control.zoom({ position: 'topright' }).addTo(map);
    markerLayer = L.layerGroup().addTo(map);

    setBasemap('dark');

    if (typeof qt !== 'undefined' && qt.webChannelTransport) {
        new QWebChannel(qt.webChannelTransport, (channel) => {
            pyBridge = channel.objects.pyController;
            console.log("Python Bridge Connected");
        });
    }

    map.on('contextmenu', (e) => {
        e.originalEvent.preventDefault();
        if (pyBridge && pyBridge.report_target_point) {
            pyBridge.report_target_point(e.latlng.lat, e.latlng.lng);
        }
        if (targetMarker) {
            targetMarker.setLatLng(e.latlng);
        } else {
            targetMarker = L.marker(e.latlng).addTo(markerLayer);
        }
    });
});

function setBasemap(name) {
    if (tileLayer) map.removeLayer(tileLayer);

    const urls = {
        'dark': 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
        'osm': 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        'satellite': 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
    };

    tileLayer = L.tileLayer(urls[name] || urls['dark'], {
        maxZoom: 19,
        attribution: '© ArmoryGIS'
    }).addTo(map);

    if (pyBridge) pyBridge.request_tile(name, map.getZoom(), 32, 20);
}

function addMarker(lat, lon, name, rangeKm) {
    markerLayer.clearLayers();
    targetMarker = null;

    L.marker([lat, lon]).addTo(markerLayer).bindPopup(`
        <b>${name}</b><br>
        Range: ${rangeKm} km
    `);

    if (rangeKm > 0) {
        L.circle([lat, lon], {
            radius: rangeKm * 1000,
            color: '#00ffcc',
            fillColor: '#00ffcc',
            fillOpacity: 0.15
        }).addTo(markerLayer);
    }

    map.fitBounds(markerLayer.getBounds().pad(0.5));
}

function loadTileFromPath(x, y, z, path) {
    console.log(`Loading cached tile: ${path}`);
}
