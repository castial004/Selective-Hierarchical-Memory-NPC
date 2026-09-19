/**
 * 2D Top-Down Town Canvas Game Engine
 */
class TownGame {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas.getContext('2d');
    this.width = this.canvas.width = 800;
    this.height = this.canvas.height = 500;

    // Player state
    this.player = {
      x: 400,
      y: 260,
      targetX: 400,
      targetY: 260,
      speed: 3.5,
      radius: 14,
      facing: 'down',
      color: '#38bdf8'
    };

    // NPC definitions & coordinates on the map
    this.npcs = {
      mira: {
        id: 'mira',
        name: 'Mira',
        role: 'Shopkeeper',
        x: 160,
        y: 130,
        color: '#f472b6',
        badgeColor: '#ec4899',
        interactRadius: 65,
        locationName: "Mira's Apothecary",
        icon: '🌿'
      },
      arun: {
        id: 'arun',
        name: 'Arun',
        role: 'Market Vendor',
        x: 640,
        y: 130,
        color: '#fbbf24',
        badgeColor: '#d97706',
        interactRadius: 65,
        locationName: "Market Stall",
        icon: '🍎'
      },
      kael: {
        id: 'kael',
        name: 'Officer Kael',
        role: 'Town Guard',
        x: 180,
        y: 380,
        color: '#60a5fa',
        badgeColor: '#2563eb',
        interactRadius: 65,
        locationName: "Guard Post",
        icon: '🛡️'
      },
      rohan: {
        id: 'rohan',
        name: 'Rohan',
        role: 'Suspect',
        x: 660,
        y: 380,
        color: '#a78bfa',
        badgeColor: '#7c3aed',
        interactRadius: 65,
        locationName: "Shadow Alley",
        icon: '🗡️'
      }
    };

    this.keys = {};
    this.nearbyNPC = null;
    this.animationFrameId = null;

    this.initControls();
    this.startLoop();
  }

  initControls() {
    window.addEventListener('keydown', (e) => {
      this.keys[e.key.toLowerCase()] = true;
      if (e.key.toLowerCase() === 'e' || e.key === ' ') {
        if (this.nearbyNPC) {
          window.interactWithNPC(this.nearbyNPC.id);
        }
      }
    });

    window.addEventListener('keyup', (e) => {
      this.keys[e.key.toLowerCase()] = false;
    });

    this.canvas.addEventListener('click', (e) => {
      const rect = this.canvas.getBoundingClientRect();
      const scaleX = this.canvas.width / rect.width;
      const scaleY = this.canvas.height / rect.height;
      const clickX = (e.clientX - rect.left) * scaleX;
      const clickY = (e.clientY - rect.top) * scaleY;

      // Check if clicked directly on an NPC
      for (const npc of Object.values(this.npcs)) {
        const dist = Math.hypot(clickX - npc.x, clickY - npc.y);
        if (dist < 35) {
          window.selectNPCTab(npc.id);
          window.interactWithNPC(npc.id);
          return;
        }
      }

      this.player.targetX = clickX;
      this.player.targetY = clickY;
    });
  }

  update() {
    // Keyboard movement
    let dx = 0;
    let dy = 0;
    if (this.keys['w'] || this.keys['arrowup']) dy -= 1;
    if (this.keys['s'] || this.keys['arrowdown']) dy += 1;
    if (this.keys['a'] || this.keys['arrowleft']) dx -= 1;
    if (this.keys['d'] || this.keys['arrowright']) dx += 1;

    if (dx !== 0 || dy !== 0) {
      const len = Math.hypot(dx, dy);
      this.player.x += (dx / len) * this.player.speed;
      this.player.y += (dy / len) * this.player.speed;
      this.player.targetX = this.player.x;
      this.player.targetY = this.player.y;
    } else {
      // Click-to-move interpolation
      const distToTarget = Math.hypot(this.player.targetX - this.player.x, this.player.targetY - this.player.y);
      if (distToTarget > 4) {
        this.player.x += ((this.player.targetX - this.player.x) / distToTarget) * this.player.speed;
        this.player.y += ((this.player.targetY - this.player.y) / distToTarget) * this.player.speed;
      }
    }

    // Boundary constraints
    this.player.x = Math.max(25, Math.min(this.width - 25, this.player.x));
    this.player.y = Math.max(25, Math.min(this.height - 25, this.player.y));

    // Check proximity to NPCs
    this.nearbyNPC = null;
    let closestDist = Infinity;
    for (const npc of Object.values(this.npcs)) {
      const d = Math.hypot(this.player.x - npc.x, this.player.y - npc.y);
      if (d < npc.interactRadius && d < closestDist) {
        this.nearbyNPC = npc;
        closestDist = d;
      }
    }
  }

  render() {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.width, this.height);

    // 1. Draw Town Ground / Cobblestone Paths
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, 0, this.width, this.height);

    // Cobble paths
    ctx.fillStyle = '#1e293b';
    ctx.fillRect(100, 230, 600, 40); // Horizontal main road
    ctx.fillRect(380, 70, 40, 360);  // Vertical crossroad

    // Central town fountain
    ctx.beginPath();
    ctx.arc(400, 250, 32, 0, Math.PI * 2);
    ctx.fillStyle = '#0ea5e9';
    ctx.fill();
    ctx.lineWidth = 4;
    ctx.strokeStyle = '#38bdf8';
    ctx.stroke();

    ctx.font = '16px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('⛲', 400, 256);

    // 2. Draw Buildings / Zones
    this.drawBuilding(70, 50, 180, 110, "Mira's Apothecary", '#831843', '#f43f5e');
    this.drawBuilding(550, 50, 180, 110, "Market Stall", '#78350f', '#f59e0b');
    this.drawBuilding(80, 320, 190, 110, "Town Guard Post", '#1e3a8a', '#3b82f6');
    this.drawBuilding(560, 320, 180, 110, "Shadow Alleyway", '#312e81', '#8b5cf6');

    // 3. Draw NPCs
    for (const npc of Object.values(this.npcs)) {
      this.drawCharacter(npc, false);
    }

    // 4. Draw Player
    this.drawCharacter(this.player, true);

    // 5. Interaction Prompt
    if (this.nearbyNPC) {
      this.drawInteractPrompt(this.nearbyNPC);
    }
  }

  drawBuilding(x, y, w, h, title, fill, stroke) {
    const ctx = this.ctx;
    ctx.save();
    ctx.fillStyle = fill;
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, 8);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = 'rgba(255, 255, 255, 0.85)';
    ctx.font = 'bold 11px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(title, x + w / 2, y + 20);
    ctx.restore();
  }

  drawCharacter(char, isPlayer) {
    const ctx = this.ctx;
    const x = char.x;
    const y = char.y;

    // Shadow
    ctx.beginPath();
    ctx.ellipse(x, y + 14, 14, 6, 0, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(0, 0, 0, 0.4)';
    ctx.fill();

    // Body
    ctx.beginPath();
    ctx.arc(x, y, 14, 0, Math.PI * 2);
    ctx.fillStyle = char.color || '#38bdf8';
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = isPlayer ? '#fff' : 'rgba(255, 255, 255, 0.4)';
    ctx.stroke();

    // Icon or Player symbol
    ctx.font = '14px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(char.icon || (isPlayer ? '👤' : '🧑'), x, y);

    // Label
    ctx.font = 'bold 10px sans-serif';
    ctx.fillStyle = '#fff';
    ctx.fillText(isPlayer ? 'You (Player)' : char.name, x, y - 20);

    // NPC role badge
    if (!isPlayer && char.role) {
      ctx.font = '8px sans-serif';
      ctx.fillStyle = char.badgeColor || '#94a3b8';
      ctx.fillText(char.role, x, y - 30);
    }
  }

  drawInteractPrompt(npc) {
    const ctx = this.ctx;
    ctx.save();
    const promptText = `Press [E] or Click to talk to ${npc.name}`;
    ctx.font = 'bold 12px sans-serif';
    const textWidth = ctx.measureText(promptText).width;

    const px = this.player.x;
    const py = this.player.y + 35;

    ctx.fillStyle = 'rgba(15, 23, 42, 0.9)';
    ctx.strokeStyle = '#06b6d4';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.roundRect(px - textWidth / 2 - 10, py - 14, textWidth + 20, 24, 6);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = '#22d3ee';
    ctx.textAlign = 'center';
    ctx.fillText(promptText, px, py + 2);
    ctx.restore();
  }

  startLoop() {
    const loop = () => {
      this.update();
      this.render();
      this.animationFrameId = requestAnimationFrame(loop);
    };
    loop();
  }
}

window.TownGame = TownGame;
