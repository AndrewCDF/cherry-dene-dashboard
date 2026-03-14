import SwiftUI

struct AlarmFeedView: View {
    @EnvironmentObject private var settings: AppSettingsStore
    @StateObject private var service = AlarmFeedService()

    var body: some View {
        NavigationStack {
            Group {
                if let errorText = service.errorText, service.items.isEmpty {
                    ContentUnavailableView(
                        "No Alarm Feed",
                        systemImage: "bell.slash",
                        description: Text(errorText)
                    )
                } else if service.items.isEmpty {
                    ContentUnavailableView(
                        "No Active Alarms",
                        systemImage: "checkmark.shield",
                        description: Text("Nothing active from sheds or the bore hole right now.")
                    )
                } else {
                    List(service.items) { item in
                        VStack(alignment: .leading, spacing: 8) {
                            HStack {
                                Text(item.source)
                                    .font(.headline)
                                Spacer()
                                Text(item.syncText)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Text(item.title)
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(.red)
                            Text(item.message)
                                .font(.body)
                        }
                        .padding(.vertical, 4)
                    }
                    .listStyle(.insetGrouped)
                }
            }
            .navigationTitle("Alarms")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        Task {
                            await service.refresh(baseURL: settings.officeDashboardURL)
                        }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                }
            }
            .safeAreaInset(edge: .bottom) {
                VStack(spacing: 4) {
                    if let lastUpdated = service.lastUpdated {
                        Text("Last updated \(lastUpdated.formatted(date: .omitted, time: .standard))")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    if let errorText = service.errorText, !errorText.isEmpty {
                        Text(errorText)
                            .font(.caption2)
                            .foregroundStyle(.red)
                    }
                }
                .padding(.bottom, 8)
            }
        }
        .onAppear {
            service.start(baseURL: settings.officeDashboardURL)
        }
        .onDisappear {
            service.stop()
        }
    }
}
