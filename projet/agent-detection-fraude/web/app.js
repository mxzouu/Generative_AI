const { createApp } = Vue;

createApp({
  data() {
    return {
      messages: [],
      draft: "",
      loading: false,
      examples: [
        { label: "Briefing : analyse les sinistres du 6 juillet 2026",
          text: "Analyse les sinistres du 2026-07-06 et donne-moi la file des cas suspects." },
        { label: "Pourquoi ce sinistre est-il suspect ?",
          text: "Pourquoi le sinistre CLM-0065 est-il suspect ? Détaille les facteurs du modèle et les cas similaires." },
        { label: "Historique d'un client",
          text: "Montre-moi l'historique du client de ce sinistre." },
      ],
    };
  },
  methods: {
    pretty(obj) {
      try { return JSON.stringify(obj, null, 2); } catch { return String(obj); }
    },
    scrollDown() {
      this.$nextTick(() => {
        const el = this.$refs.chat;
        if (el) el.scrollTop = el.scrollHeight;
      });
    },
    async send(text) {
      const content = (text ?? this.draft).trim();
      if (!content || this.loading) return;
      this.draft = "";
      this.messages.push({ role: "user", content });
      this.loading = true;
      this.scrollDown();
      try {
        const payload = this.messages.map(m => ({ role: m.role, content: m.content }));
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ messages: payload }),
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();
        this.messages.push({ role: "assistant", content: data.reply, trace: data.trace });
      } catch (e) {
        this.messages.push({ role: "assistant", content: "Erreur : " + e.message, trace: [] });
      } finally {
        this.loading = false;
        this.scrollDown();
      }
    },
  },
}).mount("#app");
