import SwiftUI

@main
struct TailDropApp: App {
    var body: some Scene {
        WindowGroup { ContentView() }
    }
}

struct ContentView: View {
    private let info = Bundle.main.infoDictionary ?? [:]
    @State private var taps = 0

    var body: some View {
        VStack(spacing: 16) {
            Text("🧩").font(.system(size: 80))
            Text("TailDrop").font(.largeTitle.bold())
            Text("Версия 5: проверяем «Обновить»").foregroundStyle(.secondary)
            Text("Build \(info["CFBundleVersion"] as? String ?? "?")")
                .font(.system(.title, design: .monospaced))
            Button("Нажато: \(taps)") { taps += 1 }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
        }
        .padding()
    }
}
