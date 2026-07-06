const { createApp } = Vue;

const SUPPLIER_BLURB = `New from AcoustiCore: the Pulse Pro Max over-ear headphones. Active noise cancellation \
with a hybrid 6-mic array, 40h battery (30h with ANC on), Bluetooth 5.3 multipoint, USB-C fast charge \
(10 min = 5h). Foldable, 250g. Wholesale 118 EUR, suggested retail 249 EUR. MOQ 50 units, 2-year warranty, \
ships week 38 from our Rotterdam warehouse. Supplier ref AC-PPM-BLK.`;

createApp({
  data() {
    return {
      messages: [],
      draft: "",
      loading: false,
      examples: [
        { label: "What noise-cancelling headphones under 300 do we carry?",
          text: "What noise-cancelling headphones under 300 do we carry?" },
        { label: "Enrich a messy supplier blurb",
          text: "Add this new supplier product to our catalog, following your add_product skill.\n\n" + SUPPLIER_BLURB },
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
        this.messages.push({ role: "assistant", content: "Error: " + e.message, trace: [] });
      } finally {
        this.loading = false;
        this.scrollDown();
      }
    },
  },
}).mount("#app");
