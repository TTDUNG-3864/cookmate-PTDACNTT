// ===================================================================
// CookMate - Application Initialization
// ===================================================================

document.addEventListener('DOMContentLoaded', function () {
  // Initialize navigation (header + footer)
  Navigation.init();
  Navigation.setupHeaderSearch();

  // Update favorites badge
  updateFavoriteBadge();

  // Initialize toast container
  CookMateUI.initToast();

  // Auto-load CookMate ChefBot AI Assistant across all pages
  if (typeof CookMateChefBot === 'undefined' && !document.getElementById('cmChefBotScript')) {
    var base = typeof getBasePath === 'function' ? getBasePath() : './';
    var botScript = document.createElement('script');
    botScript.id = 'cmChefBotScript';
    botScript.src = base + 'assets/js/chatbot.js';
    document.body.appendChild(botScript);
  } else if (typeof CookMateChefBot !== 'undefined') {
    CookMateChefBot.init();
  }

  console.log('🍳 CookMate initialized successfully');
});
